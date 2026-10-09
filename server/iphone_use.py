#!/usr/bin/env python3
"""Dependency-free local MCP stdio entrypoint for iPhone Use."""
import argparse
import base64
import collections
import fcntl
import inspect
import json
import math
import os
import queue
import re
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from wda_client import WDAClient, WDAError
from wda_controller import CALL_BUDGET, PhoneController, TYPING_FREQUENCY
from wda_setup import SetupManager, state_directory
from wda_apps import AppCatalog
from wda_screen import ScreenHub
import wda_image
from analytics import Analytics

PUAError=WDAError
VERSION="0.3.8"
SCREEN_URI="ui://iphone-use/phone-0.3.8.html"
# Codex scopes reuse to the host, chat, server and UI resource. A stable result
# ID keeps repeated READY/open/pause/resume calls in that chat on one panel,
# including after the MCP process reconnects; no device identifiers are needed.
SCREEN_SESSION_ID="iphone-use-screen"
SCREEN_META={"ui":{"csp":{"connectDomains":[],"resourceDomains":[]},"prefersBorder":False},"openai/ui":{"availableDisplayModes":["fullscreen"],"preferredDisplayMode":"fullscreen"}}
PROTOCOLS=("2025-11-25","2025-06-18","2025-03-26","2024-11-05")
# Seconds PUA may wait for animations to end before a post-action tree read; WDA_SETTLE_SECONDS overrides it.
SETTLE_SECONDS=0.8


def obj(properties,required=()):
    return {"type":"object","properties":properties,"required":list(required),"additionalProperties":False}


def string(description="",max_length=1000,enum=None):
    result={"type":"string","minLength":1,"maxLength":max_length}
    if description:result["description"]=description
    if enum:result["enum"]=enum
    return result


def num(low,high,kind="number"):
    return {"type":kind,"minimum":low,"maximum":high}


BOOL={"type":"boolean"}
SEL=obj({
 "label":string("現在の要素の正確なlabel。実際の改行と句読点は保持される。",max_length=1000),
 "label_contains":string("長い・変化するlabelの部分文字列。大文字小文字を区別する。",max_length=1000),
 "name":string("正確なname。labelと同じ場合は要素で省略される。",max_length=1000),
 "value":string("現在の正確なvalue。入力文章ではない。非同期に変わる値は省く。",max_length=1000),
 "type":string("要素に表示された種類（例：Button）。アプリのbundle IDではない。",max_length=1000),
 "enabled":{"oneOf":[{"type":"boolean"},{"type":"string","enum":["true","false"]}],"description":"任意のenabled一致条件。操作可能とは限らない。"},
 "index":{**num(0,199,"integer"),"description":"pua_findまたはambiguous_targetの候補の0始まりindex。複数候補の選択に使う。"},
 "predicate":string("単独のNSPredicate（index併用可）。安全に文字を扱うため通常は各フィールドを使う。",max_length=2000)})
SEL["description"]="label/name/value/type/enabled、label_contains、または単独predicate。rect/visible/in_viewportは観察専用。同じ位置の重複や画面内に1件だけなら解決し、別位置の複数候補はtapとindexを返す。"
SEL["examples"]=[{"label":"戻る","type":"Button"}]
SEL["minProperties"]=1
OBS=string("操作後の情報（既定none）。次の判断にtree/both、画像にはscreenshot。操作の成功証明はexpect/verifyで指定する。",enum=["none","tree","screenshot","both"])
OBS["default"]="none"
EXPECT={"expect":SEL,"observe":OBS}
VERIFY={"type":"boolean","default":False,"description":"結果を明示確認する。既定falseは1回実行し、次の必要な観察か重要な最終確認で検証する。不確実な操作を繰り返さない。"}
REGION=obj({k:num(0 if k in ("x","y") else 1,10000) for k in ("x","y","width","height")},("x","y","width","height"))
REGION["description"]="iPhoneポイントの領域。画像ピクセルではない。observation_idは任意。省略は中央。verify=trueでは現在のviewportとネイティブパネル内に収める。"
SCHEMAS={
 "observe":obj({"mode":string("独立した観察はmodeを使う（既定tree）。observeは操作後の情報。noneは独立観察には使えない。",enum=["tree","screenshot","both"]),"include_invisible":BOOL,"max_nodes":num(1,500,"integer"),"expensive_visibility":BOOL}),
 "find":obj({"selector":SEL,"limit":num(1,30,"integer")},("selector",)),
 "tap":obj({"selector":SEL,"x":num(0,10000),"y":num(0,10000),"observation_id":string("同じRuntimeの任意ID。アプリ/viewportを確認し、全画像一致や経過時間は検査しない。"),**EXPECT}),
 "swipe":obj({"direction":string("指の移動方向（既定up）。upは通常、下に続く行を表示する。",enum=["up","down","left","right"]),"region":REGION,"observation_id":string("同じRuntimeの任意ID。アプリ/viewportを確認し、数字・カルーセルの変化や経過時間は検査しない。"),"expect":SEL,"verify":{**VERIFY,"description":"falseは1回実行してXMLを確認しない。trueは移動を1回確認し、失敗時は画像を返す。数字更新だけは移動ではない。"},"max_attempts":{**num(1,2,"integer"),"default":1,"description":"旧互換の上限。2でも最初の移動未確認で止め、画像で判断する。"},"observe":OBS}),
 "type_text":obj({"selector":SEL,"text":string("入力する全文。continue_tokenがない場合、selectorと併せて使うときは必須。",max_length=10000),"allow_newlines":BOOL,"submit":BOOL,"replace":BOOL,"verify":{**VERIFY,"description":"既定falseは全文を1回入力し読み戻さない。trueは全文一致を確認し、不一致なら送信前に止める。保護欄は本人が入力する。"},**EXPECT,"continue_token":string("input_complete=falseの継続トークン。これだけを渡して元の設定で残りを入力する。",max_length=64)}),
 "press_button":obj({"name":string(enum=["home","volumeup","volumedown"]),"verify":VERIFY,**EXPECT},("name",)),
 "launch_app":obj({"bundle_id":string(),"verify":VERIFY,**EXPECT},("bundle_id",)),
 "wait":obj({"selector":SEL,"timeout_seconds":num(0,20)},("selector",)),
 "scroll_find":obj({"selector":SEL,"direction":string("指の移動方向。upは通常、下に続く行を表示する。",enum=["up","down","left","right"]),"max_swipes":{**num(0,10,"integer"),"default":1,"description":"0は検索のみ。正数は最大1回スワイプし、未解決なら次の判断用の画像を返す。"}},("selector",)),
 "collect_list":obj({"row_type":string(),"max_pages":num(1,10,"integer"),"end_selector":SEL}),
 "apps":obj({"query":string(max_length=100),"country":string(max_length=2),"source":string(enum=["auto","catalog","installed","apple"]),"limit":num(1,30,"integer")},("query",)),
 "doctor":obj({}),"ready":obj({"screenshot":{"type":"boolean","default":True,"description":"画像も確認する。falseでもstatus/session/source/viewport/ロック解除は確認する。"},"recover":{"type":"boolean","default":True,"description":"通常は省略/true。持続するlocal.pid/XCTest障害で所有者確認済みPUAを1回復旧する。明示的な診断/再起動禁止だけfalse。必要な復旧が禁止ならrecovery_required、実行中ならrecovering。どちらも未READY。"}}),"metrics":obj({"reset":{"type":"boolean","default":False,"description":"統計を返して新しい計測を開始する。"}}),
 "setup":obj({"action":string(enum=["discover","fetch","configure","build","start","stop","status"]),"udid":string(),"team_id":string(),"bundle_id":string(),"source_dir":string(max_length=4096),"local_port":num(1024,65535,"integer"),"device_port":num(1024,65535,"integer"),"job_id":string(),"wait_seconds":{**num(0,30),"description":"同じジョブを待つ上限秒数。startは既定20秒、statusは0秒。起動・復旧中は同じjob_idとwait_seconds=20でstatusを確認する。タイムアウト後もジョブは続くためstartを重ねない。"}},("action",))
}
# Each batch operation carries the same closed argument schema as its standalone tool.
BATCH_OPS=["tap","swipe","type_text","launch_app","press_button","wait","observe","scroll_find"]
SCHEMAS["batch"]=obj({"steps":{"type":"array","minItems":1,"maxItems":20,"items":{"oneOf":[obj({"op":{"type":"string","const":op},"args":SCHEMAS[op]},("op","args")) for op in BATCH_OPS]}}},("steps",))
SCHEMAS["ready"]["examples"]=[{"recover":True,"screenshot":False}]
SCHEMAS["screen"]=obj({"action":string("既定openで画面を表示。パスワード/Face IDの前にpause、本人の完了回答後だけresume。",enum=["open","pause","resume"])})
SCHEMAS["screen_frame"]=obj({"after_seq":num(0,9007199254740991,"integer"),"last_event_id":num(0,9007199254740991,"integer")})
SCHEMAS["screen_action"]=obj({"action":string("refreshで再接続、homeでホーム画面、screenshotでMacのクリップボードへ画像コピー。",enum=["refresh","home","screenshot"])},("action",))
# Tools the preview App calls itself; the model never sees them.
APP_TOOLS=("screen_frame","screen_action")
DESCRIPTIONS={
 "doctor":"端末を変更せず、MacのXcode、USB端末、署名の前提条件、PUAの状態を診断する。初回設定の診断に使う。",
 "setup":"このチャットで最初にiPhoneを使う際は、READYより先にsetup(status)を呼ぶ。対応するstart／recoverジョブを再利用するか、既存設定・ビルドで1回startする。startはサービスの起動を最大20秒待つ。未完了なら同じjob_idとwait_seconds=20でstatusを確認してからREADYへ進む。不足はiphone-use-setupで補う。許可済み起動に追加承認を挟まず、再起動禁止を守る。アプリは削除しない。",
 "ready":"このチャットの初回利用では先にsetup(status)で正常なサービス・活動ジョブを再利用し、必要な場合だけ1回startする。サービスが使える状態でREADYを取得する（recover=trueまたは省略）。ready=trueだけが操作可能を示す。以後は正常な接続を再利用する。recoverは所有者確認済みの実行障害を復旧し、停止中サービスは起動しない。recovering／recovery_requiredの案内に従い、操作を再実行しない。",
 "observe":"現在の要素・画像、iPhoneポイントのviewport、observation_idを返す。typeはXCUIElementTypeを省略、rect=[x,y,width,height]。name省略はlabel、value省略は文字、enabled／visible／in_viewport省略はtrue。要素は遮蔽され得る。画像ピクセル×image.pixel_to_point[x,y]でポイントに変換する。",
 "find":"全ツリーを取得せずselectorまたはpredicateで検索する。ツリー順のindex、種類、文字、rectを返す。selectorの各フィールドの説明はこのツールを参照する。",
 "tap":"画面内・操作可能なselector対象、またはポイント座標を1回タップする。observation_idは任意。selector失敗時は画像とtap位置を返すため、別selectorを試さず画像からx/yで押す。expectで結果条件を検証する。次の判断にページが必要ならtree／bothを指定する。",
 "swipe":"1回スワイプする。既定verify=false／observe=noneではXML確認を省く。verify=trueは幾何変化を1回確認し、失敗時はnone／treeでも画像を返し追加操作はしない。先に画像を見る。移動なしは全件取得の証拠ではない。",
 "type_text":"非保護の編集欄へ必要なUnicode全文を入力する。短い試験や毎回の読み戻しは不要。selectorなしは現在のフォーカス欄に入力し、特定失敗後は座標タップから続ける。長文は全体を1回渡し、input_complete=falseならcontinue_tokenだけで継続する。完了後にverify／submit／expect／observeを実行。verify=trueは送信前に全文を確認。改行は明示的な意図が必要、submitは既定false。不確実な入力・送信を繰り返さない。",
 "press_button":"Homeは専用homescreenを1回呼ぶ。既定では前面の待機を省略し、verify=trueはSpringBoard、expectはページを確認する。音量の効果は意味的に検証できない。",
 "launch_app":"確認したbundle IDで1回有効化する。verify=trueは最大5秒前面を待ち、expectはページを確認する。次の判断に必要な観察を同じ呼び出しで返す。不確実な起動を繰り返さない。",
 "wait":"上限付きで指定対象の出現を待つ。表示はUI条件であり業務上の正しさの証拠ではない。",
 "batch":"既知の最大20ステップをまとめる。通常の未検証操作はobserve=noneで続ける。エラー、明示検証失敗、不確実性、結果条件のない送信、長文未完了(input_continues)、時間上限(time_budget)で停止する。stopped_atから続け、完了済みを繰り返さない。次にページが必要なら最後で観察する。",
 "scroll_find":"最大1回のスワイプで操作可能な対象を探す。曖昧さ・遮蔽は即停止し、移動後の未解決は画像を返す。末尾、領域、パネルを見てから次を判断し、回数を盲目的に増やさない。",
 "collect_list":"上限付きページから要素行を取得・重複除去する。証拠と取得範囲の制限を返す。業務上の全件取得を宣言する前に照合する。",
 "metrics":"現プロセスのHTTP時間・通信量、ツール時間・応答量、次のリクエストまでの間隔を返す。本文、アプリ情報、画像は含まない。間隔にはホスト・モデル・ユーザーの時間が含まれる。reset=trueで新しい計測を開始する。"
}
DESCRIPTIONS["apps"]="実機のインストール一覧、確認済み別名、Apple検索からbundle IDを解決する。起動前に名称を調べ、IDを推測しない。ストア情報はインストールの証拠ではない。installed_verified、公開元、地域を確認する。日本のストア検索にはcountry=jpを指定する（既定cn）。"
READS={"doctor","observe","find","wait","metrics","apps"}
READS.update(("screen","screen_frame"))
DESCRIPTIONS["screen"]="CodexのサイドパネルにiPhoneのライブ画面を開くか再利用する。端末を操作しない。パスワード・Face IDの引き継ぎ前にpause、本人の完了回答後にresumeする。READYも既定で同じ画面を開く。"
DESCRIPTIONS["screen_frame"]="App専用のキャッシュフレームと操作カーソル。XML、session起動、端末操作ロックは使用しない。"
DESCRIPTIONS["screen_action"]="ユーザーが押すApp専用ボタン。プレビューの再接続、iPhoneのHome、Macへの画像コピー。認証による停止中は操作を制限する。"


def undocumented(value):
    if isinstance(value,dict):return {k:undocumented(v) for k,v in value.items() if k not in ("description","examples")}
    if isinstance(value,list):return [undocumented(v) for v in value]
    return value


# Every selector has the same fields. pua_find publishes their documentation once; other
# tools publish the same closed shape with one line pointing there.
SEL_BRIEF={**undocumented(SEL),"description":"selectorの各項目はpua_find.selectorの説明を参照。"}
OBS_BRIEF={**undocumented(OBS),"description":"次の判断のための操作後情報。既定none。"}


def published_schema(name):
    """Model-facing schema: same closed contract as SCHEMAS, with repeated documentation removed.

    Codex compacts a schema above 5KB and may drop argument branches, and all plugin
    tools share one description budget. Runtime validation keeps using SCHEMAS, without
    $ref parsing.
    """
    source=SCHEMAS[name]
    if name=="find":return source
    brief=name=="batch"
    counts={"selector":0,"observe":0}
    def count(value):
        if value==SEL:counts["selector"]+=1
        elif value==OBS:counts["observe"]+=1
        elif isinstance(value,dict):
            for item in value.values():count(item)
        elif isinstance(value,list):
            for item in value:count(item)
    count(source)
    shared={key for key,uses in counts.items() if uses>1}
    def publish(value):
        if value==SEL:return {"$ref":"#/$defs/selector"} if "selector" in shared else (undocumented(SEL) if brief else SEL_BRIEF)
        if value==OBS:return {"$ref":"#/$defs/observe"} if "observe" in shared else (undocumented(OBS) if brief else OBS_BRIEF)
        if isinstance(value,dict):return {k:publish(v) for k,v in value.items() if not (brief and k in ("description","examples"))}
        if isinstance(value,list):return [publish(v) for v in value]
        return value
    schema=publish(source)
    definitions={"selector":undocumented(SEL) if brief else SEL_BRIEF,"observe":undocumented(OBS) if brief else OBS_BRIEF}
    if shared:schema["$defs"]={key:definitions[key] for key in sorted(shared)}
    return schema


TOOLS=[{"name":"pua_"+name,"title":"Pua "+name.replace("_"," "),"description":DESCRIPTIONS[name],"inputSchema":published_schema(name),
        "annotations":{"readOnlyHint":name in READS,"destructiveHint":name not in READS,"idempotentHint":name in READS,"openWorldHint":name!="screen_frame"}} for name,schema in SCHEMAS.items()]
for tool in TOOLS:
    if tool["name"] in ("pua_ready","pua_screen"):
        tool["_meta"]={"ui":{"resourceUri":SCREEN_URI}}
    if tool["name"]=="pua_screen":
        tool.update(title="iPhoneの画面")
        tool["_meta"]["openai/ui"]={"entrypoints":[{"type":"thread"}]}
        tool["annotations"].update(readOnlyHint=False,destructiveHint=False,idempotentHint=True)
    if tool["name"][len("pua_"):] in APP_TOOLS:tool["_meta"]={"ui":{"visibility":["app"]}}
    if tool["name"]=="pua_screen_action":tool["annotations"].update(readOnlyHint=False,destructiveHint=False,idempotentHint=True)


def validate(value,schema,path="arguments"):
    if "oneOf" in schema:
        if isinstance(value,dict) and "op" in value:
            # Surface the chosen batch step's precise argument error instead
            # of hiding it behind the union of unrelated operation schemas.
            chosen=[candidate for candidate in schema["oneOf"] if candidate.get("properties",{}).get("op",{}).get("const")==value["op"]]
            if len(chosen)==1:return validate(value,chosen[0],path)
        matches=0
        for candidate in schema["oneOf"]:
            try:validate(value,candidate,path);matches+=1
            except WDAError:pass
        if matches!=1:raise WDAError("invalid_argument",f"{path} must match exactly one allowed operation schema.")
        return
    kind=schema.get("type")
    valid={"object":lambda:isinstance(value,dict),"array":lambda:isinstance(value,list),"string":lambda:isinstance(value,str),"boolean":lambda:isinstance(value,bool),"number":lambda:not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value),"integer":lambda:not isinstance(value,bool) and isinstance(value,int)}
    if kind and not valid[kind]():raise WDAError("invalid_argument",f"{path} must be {kind}.")
    if "const" in schema and value!=schema["const"]:raise WDAError("invalid_argument",f"Invalid {path} operation.")
    if "enum" in schema and value not in schema["enum"]:raise WDAError("invalid_argument",f"Invalid {path} option.")
    if kind=="object":
        props=schema.get("properties",{})
        if schema.get("additionalProperties") is False and set(value)-set(props):raise WDAError("invalid_argument",f"Unknown fields in {path}: {', '.join(sorted(set(value)-set(props)))}. Use only the declared fields.",details={"action_executed":False,"argument_path":path,"unknown_fields":sorted(set(value)-set(props)),"allowed_fields":sorted(props),"recovery":{"next_step":"Correct these fields using the current tool schema, then call once; no device action was executed."}})
        if set(schema.get("required",[]))-set(value):raise WDAError("invalid_argument",f"Missing required fields in {path}.")
        if len(value)<schema.get("minProperties",0):raise WDAError("invalid_argument",f"{path} cannot be empty.")
        for k,v in value.items():
            if k in props:validate(v,props[k],path+"."+k)
    if kind in ("number","integer") and not schema.get("minimum",-math.inf)<=value<=schema.get("maximum",math.inf):raise WDAError("invalid_argument",f"{path} is out of range.")
    if kind=="string" and not schema.get("minLength",0)<=len(value)<=schema.get("maxLength",100000):raise WDAError("invalid_argument",f"{path} has invalid length.")
    if kind=="array":
        if not schema.get("minItems",0)<=len(value)<=schema.get("maxItems",100000):raise WDAError("invalid_argument",f"{path} has invalid number of items.")
        for i,v in enumerate(value):validate(v,schema["items"],f"{path}[{i}]")


def validate_semantics(name,args):
    from wda_controller import predicate
    for k in ("selector","expect","end_selector"):
        if k in args:predicate(args[k])
    if name=="tap":
        semantic="selector" in args
        coords=all(k in args for k in ("x","y"))
        if semantic==coords or (semantic and any(k in args for k in ("x","y"))):
            raise WDAError("invalid_argument","tap requires either selector or x/y; observation_id is optional.")
    if name=="type_text":
        if "continue_token" in args:
            if len(args)!=1:raise WDAError("invalid_argument","continue_token resumes the earlier call with its own options; pass it alone.",details={"action_executed":False})
            return
        if "text" not in args:raise WDAError("invalid_argument","type_text needs text, or continue_token alone.",details={"action_executed":False})
        if any(ord(c)<32 and c not in ("\n","\r") or ord(c)==127 for c in args["text"]):raise WDAError("invalid_argument","Control characters are not allowed in text.")
        if any(c in args["text"] for c in ("\n","\r")) and not args.get("allow_newlines",False):raise WDAError("newline_requires_intent","Line breaks require explicit multiline intent.")
    if name=="launch_app" and not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+",args["bundle_id"]):raise WDAError("invalid_argument","Use the app's verified bundle ID.")
    if name=="batch":
        for step in args["steps"]:validate_semantics(step["op"],step["args"])


def copy_png(directory,data):
    """Put a PNG on the macOS clipboard; the file exists only for the duration of the copy."""
    fd,name=tempfile.mkstemp(prefix=".clipboard-",suffix=".png",dir=directory)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as stream:stream.write(data)
        # The path travels as an argument, never inside the script text.
        done=subprocess.run(["/usr/bin/osascript","-e","on run argv","-e","set the clipboard to (read (POSIX file (item 1 of argv)) as «class PNGf»)","-e","end run",name],
                            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,check=False)
        if done.returncode!=0:raise WDAError("clipboard_unavailable","The screenshot was captured but macOS did not accept it on the clipboard.")
    except (OSError,subprocess.SubprocessError) as exc:
        raise WDAError("clipboard_unavailable","The screenshot could not be copied to the clipboard.") from exc
    finally:
        try:os.unlink(name)
        except OSError:pass


def setting(name,default,low,high):
    """A bounded numeric tuning knob from the environment; anything else keeps the default."""
    try:value=float(os.environ.get(name,""))
    except ValueError:return default
    return value if math.isfinite(value) and low<=value<=high else default


class Runtime:
    def __init__(self,state_dir=None,base_url=None):
        root=state_directory(state_dir)
        self.state_dir=Path(root).expanduser().resolve();self.state_dir.mkdir(mode=0o700,parents=True,exist_ok=True);self.state_dir.chmod(0o700)
        # Configuration is private runtime data, never a project file.
        configured_url=None
        config=self.state_dir/"config.json"
        if config.is_file():
            try:configured_url="http://127.0.0.1:"+str(json.loads(config.read_text()).get("local_port",18100))
            except (ValueError,OSError):pass
        self.base_url=base_url or os.environ.get("WDA_URL") or configured_url or "http://127.0.0.1:18100"
        self.client=WDAClient(self.base_url)
        self.phone=PhoneController(self.client,self.state_dir)
        self.setup_manager=SetupManager(self.state_dir,self.base_url)
        self.apps=AppCatalog(self.state_dir,self.setup_manager)
        self.screen=ScreenHub(self.state_dir)
        self.phone.screen=self.screen
        self.phone.settle_seconds=setting("WDA_SETTLE_SECONDS",SETTLE_SECONDS,0,2)
        self.phone.call_budget=setting("WDA_CALL_BUDGET_SECONDS",CALL_BUDGET,5,240)
        self.phone.typing_frequency=int(setting("WDA_TYPING_FREQUENCY",TYPING_FREQUENCY,5,120))
        # One entry per model-facing response: size, and the idle gap before its request.
        self.responses=collections.deque(maxlen=500)
        self._replied_at=None
        self._device_lookup=None
        self.analytics=Analytics(self.state_dir,VERSION)

    def call(self,name,args):
        started=time.monotonic();data=None;error=None
        try:
            data=self._dispatch(name,args)
            return data
        except WDAError as exc:
            error=exc.code
            raise
        except Exception:
            error="internal_error"
            raise
        finally:
            try:self.analytics.tool_result(name,args,data,(time.monotonic()-started)*1000,error)
            except Exception:pass

    def _dispatch(self,name,args):
        # PUA has one active session. Serialize independent Codex MCP processes
        # sharing this runtime, and share only this plugin's session identity.
        if not isinstance(name,str) or not name.startswith("pua_") or name[4:] not in SCHEMAS:raise WDAError("unknown_tool","Unknown PUA tool.")
        validate(args,SCHEMAS[name[4:]]);validate_semantics(name[4:],args)
        if name in ("pua_screen","pua_screen_frame","pua_screen_action"):self.identify_device()
        # Cached preview polling does not share the PUA action/session lock.
        if name=="pua_screen_frame":return self.screen.frame(**args)
        if name=="pua_screen_action":return self.screen_action(args["action"])
        if name=="pua_screen":
            action=args.get("action","open")
            if action=="pause":self.screen.set_paused(True)
            elif action=="resume":self.screen.set_paused(False)
            return self.screen.start()
        lock_path=self.state_dir/"operation.lock"
        cache_path=self.state_dir/"session.json"
        with lock_path.open("a") as lock:
            lock_path.chmod(0o600)
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise WDAError("device_busy","Another iPhone Use operation is running. Wait for it to finish before continuing; no action was executed.")
            try:
                if cache_path.is_file() and hasattr(self.client,"session_id"):
                    try:
                        cached=json.loads(cache_path.read_text())
                        sid=cached.get("session_id","")
                        if cached.get("url")==self.base_url and isinstance(sid,str) and re.fullmatch(r"[A-Za-z0-9-]{1,128}",sid):self.client.session_id=sid
                    except (ValueError,OSError,AttributeError):pass
                return self._call(name,args)
            finally:
                sid=getattr(self.client,"session_id",None)
                if sid:
                    task_temp=self.state_dir/("session-"+str(os.getpid())+".tmp")
                    try:
                        fd=os.open(task_temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                        with os.fdopen(fd,"w") as stream:json.dump({"url":self.base_url,"session_id":sid},stream)
                        os.replace(task_temp,cache_path)
                    finally:
                        if task_temp.exists():task_temp.unlink()
                elif hasattr(self.client,"session_id") and cache_path.exists():cache_path.unlink()
                fcntl.flock(lock,fcntl.LOCK_UN)

    def identify_device(self):
        """Find the phone's model name for the preview header once, away from the request path."""
        if self._device_lookup is not None:return
        def lookup():
            udid=self.setup_manager.config.get("udid")
            # Nothing is configured yet: there is no phone to name, and nothing to look up.
            if not isinstance(udid,str) or not udid:return
            cache=self.state_dir/"device.json"
            try:
                known=json.loads(cache.read_text())
                if known.get("udid")==udid and isinstance(known.get("model"),str):
                    self.screen.device={"model":known["model"][:60]};return
            except (OSError,ValueError,AttributeError):pass
            try:
                model=next((d.get("model") for d in self.setup_manager.discover().get("devices",[]) if udid and d.get("udid")==udid),None)
                if isinstance(model,str) and model:
                    self.screen.device={"model":model[:60]}
                    fd=os.open(cache,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                    with os.fdopen(fd,"w") as stream:json.dump({"udid":udid,"model":model},stream)
            except Exception:
                # The header falls back to a generic name; the preview must never fail over a label.
                pass
        self._device_lookup=threading.Thread(target=lookup,name="wda-device-model",daemon=True)
        self._device_lookup.start()

    def screen_action(self,action):
        """Toolbar of the preview App: the user's own click, outside the model's tool sequence."""
        if action=="refresh":
            pause_id=self.screen.reconnect_pause_id()
            state=self.screen.restart()
            probe=WDAClient(self.base_url,timeout=2)
            try:
                ready=(probe.request("GET","/status").get("value") or {}).get("ready") is True
                if ready:
                    if probe.request("GET","/wda/locked").get("value") is False:
                        # Clicking refresh is the user's explicit request to resume.
                        self.screen.resume_after_unlock(pause_id,explicit=True)
                    else:self.screen.set_paused(True,reason="device_locked")
            except WDAError:ready=False
            finally:probe.close()
            return {"ok":True,"action":action,"service_ready":ready,**state,**self.screen.pause_status()}
        if self.screen.paused():
            raise WDAError("preview_paused","The preview is paused while the user authenticates on the iPhone. No capture or phone action was made.",details={"action_executed":False})
        client=WDAClient(self.base_url,timeout=8)
        try:
            if action=="home":
                lock_path=self.state_dir/"operation.lock"
                with lock_path.open("a") as lock:
                    lock_path.chmod(0o600)
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:raise WDAError("device_busy","The iPhone is in the middle of another operation. Try again in a moment; nothing was sent.",details={"action_executed":False})
                    try:client.request("POST","/wda/homescreen",{})
                    finally:fcntl.flock(lock,fcntl.LOCK_UN)
                self.phone.external_action()
                return {"ok":True,"action":action}
            encoded=client.request("GET","/screenshot").get("value")
            try:data=base64.b64decode(encoded,validate=True)
            except (ValueError,TypeError):raise WDAError("invalid_response","Invalid screenshot encoding.")
            size=wda_image.png_size(data[:32])
            if size is None:raise WDAError("invalid_response","PUA screenshot is not PNG.")
            copy_png(self.state_dir,data)
            return {"ok":True,"action":action,"copied":True,"width":size[0],"height":size[1]}
        finally:client.close()

    @staticmethod
    def channel_fault(error):
        text=str(error).lower()
        if "not authorized for performing ui testing actions" in text or ("xctdaemonerrordomain" in text and "code=41" in text):
            return "xctest_authorization"
        if error.code=="pua_foreground_unavailable" or ("local.pid." in text and error.code=="stale element reference"):
            return "foreground_unavailable"
        return None

    def ready_once(self,screenshot):
        try:lock_pause=self.screen.locked_pause_id()
        except Exception:lock_pause=None
        status=self.client.request("GET","/status").get("value") or {}
        if status.get("ready") is not True:raise WDAError("not_ready","PUA is not accepting commands. Run pua_doctor and inspect setup status.")
        if self.client.request("GET","/wda/locked").get("value") is not False:raise WDAError("phone_locked","Unlock the iPhone yourself, keep it awake, and verify READY again.")
        sid=self.client.ensure_session()
        observation=self.phone.observe("both" if screenshot else "tree")
        if observation.get("total_nodes",0)==0 and self.setup_manager.mirroring_running():raise WDAError("mirroring_conflict","iPhone Mirroring is running and PUA exposes an empty phone tree. Quit Mirroring, unlock if needed, then verify READY again.")
        result={"ready":True,"state":"ready","proof":{"status_ready":True,"phone_unlocked":True,"session_usable":bool(sid),"foreground_resolved":True,"source_readable":True,"viewport_readable":True,"screenshot_readable":screenshot},"observation":observation}
        try:
            self.screen.resume_after_unlock(lock_pause)
            result["preview"]=self.screen.pause_status()
        except Exception:pass  # Display state must not invalidate a healthy control channel.
        return result

    def recovering_result(self,info,screenshot,recover,retried=False,cause=None):
        info=dict(info)
        job_id=info["job_id"]
        self.client.close();self.client.session_id=None;self.phone.reset()
        info.update(status_tool="pua_setup",status_arguments={"action":"status","job_id":job_id},next_tool="pua_ready",next_arguments={"screenshot":screenshot,"recover":recover},retry_after_seconds=1,replay_action=False)
        result={"ready":False,"state":"recovering","message":"Owned PUA recovery is running in the background. Poll the supplied setup job; once the service is reachable, run READY again. No phone task may proceed until ready=true. Do not replay the failed user action.","action_executed":False,"category":"channel_runtime","session_read_retried":retried,"recovery":info}
        if cause is not None:result["cause"]=cause.as_dict()
        return result

    def ready(self,screenshot=True,recover=True):
        pending=self.setup_manager.pending_recovery() if hasattr(self.setup_manager,"pending_recovery") else None
        if pending and pending.get("job_id"):
            # The old listener may still answer before the owned worker stops
            # it. Never return that soon-to-be-invalid session as READY.
            return self.recovering_result(pending,screenshot,recover)
        retried=False
        try:return self.ready_once(screenshot)
        except WDAError as error:
            original=error
        fault=self.channel_fault(original)
        if fault=="foreground_unavailable":
            # The one retry is a fresh session/source read, never a replay of
            # a click, key, submission or an element ID from an older session.
            self.client.close();self.client.session_id=None;self.phone.reset()
            retried=True
            try:
                result=self.ready_once(screenshot)
                result["recovery"]={"state":"read_recovered","session_recreated":True,"replayed_action":False}
                return result
            except WDAError as error:
                original=error;fault=self.channel_fault(error)
        if original.code=="phone_locked":raise original
        pending=self.setup_manager.pending_recovery() if hasattr(self.setup_manager,"pending_recovery") else None
        if pending and original.code in ("pua_unreachable","not_ready","invalid session id","pua_foreground_unavailable","stale element reference","unknown error","invalid argument"):
            recovery={"ok":True,"recovery":pending,"job_id":pending.get("job_id")}
        elif fault and recover:
            recovery=self.setup_manager.recover()
        else:
            if fault:
                return {"ready":False,"state":"recovery_required","reason":"recovery_disabled","message":"The PUA/XCTest channel needs recovery, but this call explicitly disabled service restart. No recovery was started. Resume with recover=true only when allowed by the current user instructions.","action_executed":False,"category":"channel_runtime","session_read_retried":retried,"cause":original.as_dict(),"recovery":{"state":"disabled","next_tool":"pua_ready","next_arguments":{"screenshot":screenshot,"recover":True},"permission_note":"Honor any user instruction forbidding restart; do not automatically override it.","replay_action":False}}
            if original.code in ("pua_unreachable","not_ready"):
                # A stopped service needs setup/start, not an owned-listener restart.
                # Keep the failure truthful, but give the next read-only diagnostic.
                original.details.update(ready=False,action_executed=False,initialization_required=True,
                    recovery={"next_tool":"pua_setup","next_arguments":{"action":"status"},"replay_action":False,
                              "next_step":"Continue initialization; do not end the phone task solely because PUA is not started. Inspect configured/jobs/service: reuse an active start/recovery job, or start once from the existing configuration/build if permitted, then verify READY. Missing prerequisites use iphone-use-setup. Honor explicit no-restart or read-only instructions."})
            raise original
        info=dict(recovery.get("recovery") or {})
        job_id=recovery.get("job_id") or info.get("job_id")
        if recovery.get("ok") and job_id:
            info["job_id"]=job_id
            return self.recovering_result(info,screenshot,recover,retried,original)
        info.update(next_steps=recovery.get("next_steps",[]),replay_action=False)
        raise WDAError("pua_recovery_required","Automatic PUA recovery was not started: "+str(recovery.get("error","service ownership could not be proven")),details={"ready":False,"action_executed":False,"category":"channel_runtime","session_read_retried":retried,"cause":original.as_dict(),"recovery":info})

    def _call(self,name,args):
        if not isinstance(name,str) or not name.startswith("pua_") or name[4:] not in SCHEMAS:raise WDAError("unknown_tool","Unknown PUA tool.")
        op=name[4:];validate(args,SCHEMAS[op]);validate_semantics(op,args)
        start=time.monotonic();error=None;activity=None
        try:
            if op not in ("doctor","apps","setup","metrics"):
                try:activity=self.screen.begin(op)
                except Exception:pass
            if op=="doctor":return self.setup_manager.doctor()
            if op=="apps":return self.apps.lookup(**args)
            if op=="setup":
                manager=self.setup_manager
                candidate_url=self.base_url
                if args["action"]=="configure" and "local_port" in args:
                    candidate_url="http://127.0.0.1:"+str(args["local_port"])
                    manager=SetupManager(self.state_dir,candidate_url)
                result=manager.setup(**args)
                if result.get("ok") and args["action"] in ("stop","configure","start"):
                    self.client.close();self.client.session_id=None;self.phone.reset()
                if result.get("ok") and args["action"]=="configure" and "local_port" in args:
                    self.base_url=candidate_url;self.setup_manager=manager
                    self.apps.setup_manager=manager
                    self.client=WDAClient(self.base_url);self.phone.client=self.client
                return result
            if op=="ready":
                try:self.screen.start()
                except Exception:pass
                return self.ready(**args)
            if op=="metrics":
                result=self.metrics()
                if args.get("reset"):
                    self.client.clear_metrics();self.phone.tool_records.clear();self.responses.clear();self._replied_at=None
                return result
            if op in ("tap","swipe","type_text","launch_app","press_button","batch","scroll_find","collect_list"):
                if self.client.request("GET","/wda/locked").get("value") is not False:raise WDAError("phone_locked","Unlock the iPhone yourself before operations; observe again afterward.")
            return getattr(self.phone,op)(**args)
        except WDAError as exc:
            error=exc.code
            if exc.code=="phone_locked" or (exc.code=="not_editable" and exc.details.get("secure_field")):
                try:self.screen.set_paused(True,reason="device_locked" if exc.code=="phone_locked" else "authentication")
                except Exception:pass
            if op in READS:
                exc.details.setdefault("action_executed",False)
            if self.channel_fault(exc):
                exc.details.update(category="channel_runtime",recovery={"tool":"pua_ready","arguments":{"screenshot":False},"replay_action":False})
            raise
        except (ValueError,TypeError) as exc:error="invalid_argument";raise WDAError(error,str(exc)) from exc
        finally:
            if activity is not None:
                try:self.screen.end(activity)
                except Exception:pass
            self.phone.tool_records.append({"tool":name,"seconds":round(time.monotonic()-start,4),"error":error})

    def metrics(self):
        records=list(self.phone.tool_records);responses=list(self.responses)
        def grouped(items,fields):
            groups={}
            for item in items:
                entry=groups.setdefault(item["tool"],{"count":0,**{field:0 for field in fields}})
                entry["count"]+=1
                for field in fields:entry[field]=round(entry[field]+(item[field] or 0),4)
            return groups
        waits=[item["wait_seconds"] for item in responses if item["wait_seconds"] is not None]
        return {**self.client.metrics(),
                "tools":{"count":len(records),"seconds":round(sum(r["seconds"] for r in records),4),"errors":sum(bool(r["error"]) for r in records),
                         "by_tool":grouped([{**r,"errors":int(bool(r["error"]))} for r in records],("seconds","errors"))},
                "responses":{"count":len(responses),"text_bytes":sum(r["text_bytes"] for r in responses),"image_bytes":sum(r["image_bytes"] for r in responses),
                             "by_tool":grouped(responses,("text_bytes","image_bytes"))},
                "rounds":{"count":len(responses),"waits":len(waits),"wait_seconds":round(sum(waits),3),
                          "median_wait_seconds":round(statistics.median(waits),3) if waits else None,"max_wait_seconds":round(max(waits),3) if waits else None,
                          "scope":"Time from one tool response to the next tool request: host, model and user time together. A long wait may be the user, not the model."},
                "latency_scope":"HTTP, tool time and response sizes are measured here. The wait between calls is observed, not controlled; this plugin cannot split it into model, host and user time."}

    def note_response(self,name,result,arrived):
        """Record what one model-facing response cost and how long the previous one waited for it."""
        if name=="pua_screen_frame":return
        content=result.get("content",[])
        self.responses.append({"tool":name if isinstance(name,str) else "invalid",
            "text_bytes":sum(len(item["text"].encode()) for item in content if item.get("type")=="text"),
            "image_bytes":sum(len(item["data"]) for item in content if item.get("type")=="image"),
            "wait_seconds":None if self._replied_at is None else max(0.0,arrived-self._replied_at)})

    def replied(self):self._replied_at=time.monotonic()

    def close(self):
        try:self.screen.close();self.client.close()
        finally:self.analytics.close()


def result_content(data,structured=False):
    """One compact JSON text block, plus the screenshot when the result carries one.

    structuredContent is left out on purpose: a host that receives it may give the model
    only that object and drop every content block, including the image.
    """
    content=[{"type":"text","text":json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(",",":"))}]
    image=data.get("image") or data.get("observation",{}).get("image")
    if not image and isinstance(data.get("error"),dict):image=data["error"].get("observation",{}).get("image")
    if not image and data.get("results"):
        last=data["results"][-1];image=last.get("image") or last.get("observation",{}).get("image")
    if image and Path(image["path"]).is_file():content.append({"type":"image","data":base64.b64encode(Path(image["path"]).read_bytes()).decode(),"mimeType":image.get("mimeType","image/png")})
    result={"content":content,"isError":"error" in data}
    if structured:result["structuredContent"]=data
    return result


def tool_result(runtime,params):
    name=params.get("name")
    try:
        data=runtime.call(name,params.get("arguments",{}))
        # The preview App reads structuredContent; frames never become model text.
        if name=="pua_screen_frame":return {"content":[],"structuredContent":data,"isError":False}
        result=result_content(data,structured=name in ("pua_screen","pua_screen_action"))
        if name in ("pua_ready","pua_screen"):
            result["_meta"]={"openai/widgetSessionId":SCREEN_SESSION_ID}
        return result
    except WDAError as exc:return result_content({"error":exc.as_dict()},structured=name=="pua_screen_action")
    except Exception as exc:
        print("iphone-use tool failure: "+type(exc).__name__,file=sys.stderr)
        return result_content({"error":{"code":"internal_error","message":"Local tool failed; inspect setup status or local stderr.","uncertain":True}})


INSTRUCTIONS=(
 "PUAはPhone Use Agent。ツール名はpua_で始まる。ユーザーには日本語で案内する。設定前にiphone-use-setup、作業前にiphone-useを読む。このチャットの初回利用では、READYより先にpua_setup(action=status)で正常なサービス・活動ジョブを再利用し、必要な場合だけstartを1回呼ぶ。サービスが使える状態になってからpua_ready(recover=true, screenshot=false)でready=trueを確認し、そのobservationと正常な接続を再利用する。 "
 "startは最大20秒待ち、service.ready=trueなら直接READYへ進む。未完了なら同じjob_idとwait_seconds=20でsetup(status)を確認し、startを重ねない。READYの失敗を待ってからsetupを始めない。READYがpua_unreachable/not_readyなら同じ初期化を続ける。不足はsetupスキルで補う。recoverは実行障害の復旧で、コールドスタートではない。recoveringは同じジョブを追う。明示的な診断、起動・再起動禁止を守る。 "
 "画面はREADYで同じサイドパネルを開くか再利用する。setup/復旧/pause/resumeで同じパネルを保持する。閉じた画面はpua_screenで開き、表示中の更新には使わない。開くだけではREADYや追加承認を意味しない。プレビューのフレームはモデルの観察や最終確認の代わりにならない。 "
 "結果は簡潔なJSON。typeはXCUIElementTypeを省略、rect=[x,y,width,height]はiPhoneポイント。name省略はlabel、value省略は文字、enabled/visible/in_viewport省略はtrue。固定ヘッダーやパネルが要素を覆う場合がある。 "
 "画像は同じ結果のimageブロック。functions.execではimage(block)、text(block.text)で転送し、全結果やbase64をtextにしない。転送不能ならview_imageでimage.path/error.observation.image.pathを開く。画像ピクセル×image.pixel_to_point[x,y]をiPhoneポイントへ変換する。独立観察はmode、操作後はobserve。 "
 "selectorは現在のlabel/name/value/typeを写し、長い・変化するラベルはlabel_contains。同じ場所の重複や画面内1件はツールが解決する。selector/焦点の失敗、検索未解決、移動なし、領域の遮蔽/文脈変化、入力不一致、期待ページ不在は必ず添付画像を先に見る。なければpua_observe(mode=screenshot)を1回呼ぶ。画像から終了、パネル処理、領域/方向変更、座標タップ、残りの処理を判断する。scroll_findは未解決後に連続スワイプしない。tap_point/candidatesは遮蔽なしを証明しない。見える入力欄をタップし、selectorなしのtype_textで入力する。座標や焦点失敗は画像から位置を選び直し、同じ座標やラベル変更・ツリー再読を先に繰り返さない。schema/接続/認証は対応手順で復旧し、不確実な操作を再実行しない。未知bundle IDはpua_apps。 "
 "通常操作はobserve=none、verify=false。verified=false/verification_deferred=trueは正常で、個別確認を要求しない。次の判断に必要なら同じ操作でtree/bothを返し進捗も確認する。既知の手順はbatchへまとめる。未知対象への連続した推測スワイプはbatchに入れず、次ページを先に見て境界が隠れた場合は画像を使う。重要な結果にはexpect/verify。長文は全文を1回渡し、input_complete=falseならcontinue_tokenだけで継続する。input_continues/time_budgetで停止したbatchはstopped_atから続ける。 "
 "完了前に重要な最終結果を確認する。明確な失敗を観察してから修正し、不確実な入力/送信や実行済みの複数手順を全部やり直さない。no_scroll_progressは空データや全件取得の証拠ではない。 "
 "アプリのパスワード/Face IDはpua_screen(action=pause)。phone_lockedはdevice_lockedで自動停止するので追加pauseで上書きしない。端末呼び出しを止め、ホストの質問ツール（Defaultはrequest_user_input_async）を使う。先頭の選択肢は必ず「完了したので続けてください」。非同期戻り値や初期選択は回答ではない。本人の実際の完了回答後、アプリ/旧unknown停止はresumeし新しく観察する。ロック解除はREADYを1回確認し、同じdevice_lockedだけを解除する。READY/openはアプリ認証/unknown停止を解除しない。新しい状態から残りを続ける。 "
 "action_complete/verifiedは全作業の完了ではない。成果物を追跡し、短い進捗を伝え、残りがある間は続ける。完了または具体的な障害でfinalにする。MCPバインドが使えない場合はスキルのRuntime入口で同じ操作ロックを保つ。 "
)


def serve(runtime):
    """Read requests on this thread; run phone tools in order on one worker.

    The preview App polls frames several times a second. Answering those, pings and the
    catalog here keeps the preview live and the host responsive while a long phone
    operation is still running. Phone tools stay strictly sequential.
    """
    writing=threading.Lock()
    def send(response):
        line=json.dumps(response,ensure_ascii=False,allow_nan=False)
        with writing:print(line,flush=True)
    jobs=queue.Queue()
    def work():
        while True:
            job=jobs.get()
            if job is None:return
            ident,params,arrived=job
            result=tool_result(runtime,params)
            runtime.note_response(params.get("name"),result,arrived)
            send({"jsonrpc":"2.0","id":ident,"result":result})
            runtime.replied()
    worker=threading.Thread(target=work,name="wda-tools",daemon=True)
    worker.start()
    try:
        for line in sys.stdin:
            request=None
            try:
                if len(line)>1024*1024:raise ValueError("Request exceeds 1 MiB")
                request=json.loads(line,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
                if not isinstance(request,dict) or request.get("jsonrpc")!="2.0" or not isinstance(request.get("method"),str):raise ValueError("Invalid request")
                if "id" not in request:continue
                ident=request["id"]
                if isinstance(ident,bool) or not isinstance(ident,(str,int)):raise ValueError("Invalid identifier")
                params=request.get("params",{})
                if not isinstance(params,dict):raise WDAError("invalid_argument","params must be an object.")
                method=request["method"]
                if method=="initialize":
                    offered=params.get("protocolVersion")
                    result={"protocolVersion":offered if offered in PROTOCOLS else PROTOCOLS[0],"capabilities":{"tools":{"listChanged":False},"resources":{"listChanged":False}},"serverInfo":{"name":"iphone-use","version":VERSION},"instructions":INSTRUCTIONS}
                    try:runtime.analytics.start()
                    except Exception:pass
                elif method=="ping":result={}
                elif method=="tools/list":result={"tools":TOOLS}
                elif method=="resources/list":
                    result={"resources":[{"uri":SCREEN_URI,"name":"iPhone Use Screen","title":"iPhoneの画面","mimeType":"text/html;profile=mcp-app","_meta":SCREEN_META}]}
                elif method=="resources/read":
                    if params.get("uri")!=SCREEN_URI:raise WDAError("invalid_argument","Unknown screen resource URI.")
                    html=(Path(__file__).resolve().parents[1]/"assets/phone-screen.html").read_text()
                    result={"contents":[{"uri":SCREEN_URI,"mimeType":"text/html;profile=mcp-app","text":html,"_meta":SCREEN_META}]}
                elif method=="tools/call":
                    arrived=time.monotonic()
                    if params.get("name") not in ("pua_screen_frame","pua_screen","pua_screen_action"):
                        jobs.put((ident,params,arrived));continue
                    # Preview polls, its toolbar and opening or pausing the panel never wait behind a phone operation.
                    result=tool_result(runtime,params)
                    if params.get("name")=="pua_screen":
                        runtime.note_response("pua_screen",result,arrived);runtime.replied()
                else:
                    send({"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":"Method not found"}});continue
                response={"jsonrpc":"2.0","id":ident,"result":result}
            except WDAError as exc:response={"jsonrpc":"2.0","id":request.get("id") if isinstance(request,dict) else None,"error":{"code":-32602,"message":str(exc)}}
            except (ValueError,TypeError,KeyError):response={"jsonrpc":"2.0","id":request.get("id") if isinstance(request,dict) else None,"error":{"code":-32700 if request is None else -32600,"message":"Parse error" if request is None else "Invalid request"}}
            send(response)
    finally:
        # Finish the phone operation already accepted, then stop: its outcome must be reported.
        jobs.put(None);worker.join()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir");parser.add_argument("--url");parser.add_argument("--doctor",action="store_true");parser.add_argument("--ready",action="store_true")
    args=parser.parse_args();runtime=Runtime(args.state_dir,args.url)
    try:
        if args.doctor or args.ready:
            try:data=runtime.call("pua_doctor" if args.doctor else "pua_ready",{})
            except WDAError as exc:data={"error":exc.as_dict()}
            print(json.dumps(data,ensure_ascii=False));return 1 if "error" in data or (args.ready and data.get("ready") is not True) else 0
        serve(runtime);return 0
    finally:runtime.close()


if __name__=="__main__":sys.exit(main())
