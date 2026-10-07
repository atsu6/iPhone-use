"""Optimistic iPhone operations with optional observations and explicit verification."""
import base64
import collections
import datetime as dt
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote
from wda_client import WDAError

ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


def fail(code, message, **details):
    raise WDAError(code, message, details=details)


def stale(message,reason,scope="page",**details):
    fail("stale_observation",message,action_executed=False,reason=reason,freshness_scope=scope,
         recovery={"next_tool":"wda_observe","next_arguments":{"mode":"both"},"same_observation_retry":False,"replay_action":False,
                   "next_step":"Inspect the current app and viewport before reusing coordinates. An observation ID is optional; changing text, numbers or screenshot pixels does not invalidate its app/viewport context."},**details)


def finite(value, name, low=0, high=10000):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
        fail("invalid_argument", f"{name} must be a finite number in [{low}, {high}].")
    return value


def integer(value, name, low, high):
    finite(value, name, low, high)
    if not isinstance(value,int):
        fail("invalid_argument", f"{name} must be an integer.")
    return value


def action_result(function):
    @wraps(function)
    def wrapped(self,*args,**kwargs):
        before=self.accepted_actions
        try:return function(self,*args,**kwargs)
        except WDAError as error:
            if self.accepted_actions>before:
                error.details.update(action_executed=True,action_complete=False)
                if function.__name__=="swipe":
                    error.details.setdefault("attempts",self.accepted_actions-before)
                error.details.setdefault("verification_required","At least one phone action was accepted before the error. Read actual state; do not automatically replay the operation.")
            raise
    return wrapped


def predicate_literal(value):
    # NSPredicate rejects literal line breaks inside quoted strings. Its Unicode
    # escapes preserve exact text, including a literal backslash followed by n.
    return "".join("\\\\" if c=="\\" else "\\'" if c=="'" else f"\\u{ord(c):04x}" if ord(c)<32 or ord(c)==127 or c in "\u2028\u2029" else c for c in value)


def predicate(selector):
    if not isinstance(selector,dict) or not selector or set(selector)-{"label","name","value","type","enabled","predicate"}:
        fail("invalid_selector", "Use label/name/value/type/enabled, or a standalone WDA predicate.")
    if "predicate" in selector:
        if len(selector)!=1:
            fail("invalid_selector", "predicate cannot be mixed with exact fields.")
        result = selector["predicate"]
        if not isinstance(result,str) or not 1 <= len(result) <= 2000:
            fail("invalid_selector", "predicate must have 1..2000 characters.")
        return result
    clauses=[]
    for key,value in selector.items():
        if key=="enabled":
            if not isinstance(value,bool) and value not in ("true","false"):
                fail("invalid_selector","enabled must be a boolean or the exact tree string true/false.")
            literal="true" if value is True or value=="true" else "false"
            clauses.append("enabled == "+literal)
            continue
        if not isinstance(value,str) or not 1 <= len(value) <= 1000:
            fail("invalid_selector", "Selector fields must be nonempty strings up to 1000 characters.")
        if "\x00" in value:
            fail("invalid_selector", "Exact selector strings cannot contain NUL; NSPredicate cannot match that character reliably.")
        if key=="type" and not value.startswith("XCUIElementType"):
            value="XCUIElementType"+value
        escaped=predicate_literal(value)
        clauses.append(f"{key} == '{escaped}'")
    return " AND ".join(clauses)


class PhoneController:
    def __init__(self, client, state_dir):
        self.client, self.state_dir = client, Path(state_dir)
        self.snapshots=collections.OrderedDict()
        self.tool_records=collections.deque(maxlen=500)
        self.accepted_actions=0
        self.screen=None
        self._screen_viewport=None
        self._screen_targets={}

    def screen_event(self,kind,**kwargs):
        # Display telemetry must never change, retry or delay a phone action
        # with extra WDA requests. No selector, input text or app data is sent.
        if self.screen is not None:
            try:self.screen.gesture(kind,viewport=self._screen_viewport,**kwargs)
            except Exception:pass

    def post(self,path,payload,timeout=None,session=True):
        if path=="/wda/tap":self.screen_event("tap",point={"x":payload["x"],"y":payload["y"]})
        elif path.endswith("/click") and path[:-6] in self._screen_targets:
            self.screen_event("tap",point=self._screen_targets[path[:-6]])
        elif path=="/wda/dragfromtoforduration":
            self.screen_event("drag",**{"from_point":{"x":payload["fromX"],"y":payload["fromY"]},"to_point":{"x":payload["toX"],"y":payload["toY"]},"duration_ms":max(300,min(3000,int((payload.get("duration",0)+.35)*1000)))})
        result=self.client.session("POST",path,payload,timeout=timeout) if session else self.client.request("POST",path,payload,timeout=timeout)
        self.accepted_actions+=1
        return result

    def viewport(self):
        v=self.client.session("GET", "/window/size")
        if not isinstance(v,dict):
            fail("invalid_response", "Missing viewport.")
        finite(v.get("width"),"width",1,10000);finite(v.get("height"),"height",1,10000)
        if self.screen is not None and v!=self._screen_viewport:
            self._screen_viewport={"width":v["width"],"height":v["height"]}
            try:self.screen.set_viewport(self._screen_viewport)
            except Exception:pass
        return {"width":v["width"],"height":v["height"],"units":"iPhone points"}

    def active_app(self,timeout=None):
        result=self.client.request("GET", "/wda/activeAppInfo",timeout=timeout).get("value") or {}
        app=result.get("bundleId")
        if not isinstance(app,str) or not app or app.startswith("local.pid."):
            fail("wda_foreground_unavailable","WDA cannot resolve a running foreground application. This is a WDA/XCTest channel problem, not a selector or schema error.",foreground_app=app,recovery={"tool":"wda_ready","arguments":{"screenshot":False},"replay_action":False})
        return app

    def tree(self, include_invisible=False, expensive_visibility=False):
        path="/source?format=xml"
        if not expensive_visibility:
            path+="&excluded_attributes=visible"
        raw=self.client.session("GET",path)
        if not isinstance(raw,str):
            fail("invalid_response", "WDA source is not XML text.")
        try:
            tree=ET.fromstring(raw)
        except ET.ParseError as exc:
            fail("invalid_response", f"WDA XML parse failed: {exc}.")
        viewport=self.viewport()
        nodes=[]
        for element in tree.iter():
            a=element.attrib
            if not any(a.get(k) for k in ("label","name","value")) and a.get("type") not in ("XCUIElementTypeAlert","XCUIElementTypeSheet"):
                continue
            try:
                rect={k:float(a.get(k,0)) for k in ("x","y","width","height")}
            except ValueError:
                continue
            if not all(math.isfinite(n) for n in rect.values()):
                continue
            intersects=rect["width"]>0 and rect["height"]>0 and rect["x"]<viewport["width"] and rect["y"]<viewport["height"] and rect["x"]+rect["width"]>0 and rect["y"]+rect["height"]>0
            if not include_invisible and (not intersects or a.get("visible")=="false"):
                continue
            if a.get("type") in ("XCUIElementTypeApplication","XCUIElementTypeWindow"):
                continue
            node={k:a[k] for k in ("type","name","label","value","enabled","visible") if k in a}
            node["rect"]=rect;node["in_viewport"]=intersects
            nodes.append(node)
        return nodes,viewport

    def region_nodes(self,nodes,region=None):
        if region:
            x,y,w,h=region["x"],region["y"],region["width"],region["height"]
            nodes=[n for n in nodes if x<=n["rect"]["x"]+n["rect"]["width"]/2<=x+w and y<=n["rect"]["y"]+n["rect"]["height"]/2<=y+h]
        # Ignore status bar clocks/battery values. Compare visible content and geometry.
        nodes=[n for n in nodes if n["type"]!="XCUIElementTypeStatusBar" and n["rect"]["y"]>=45]
        return nodes

    def signature(self,nodes,region=None):
        return hashlib.sha256(json.dumps(self.region_nodes(nodes,region),ensure_ascii=False,sort_keys=True).encode()).hexdigest()

    def remember(self,nodes,viewport,app,image_signature=None,has_tree=True):
        ident=uuid.uuid4().hex
        self.snapshots[ident]={"time":time.monotonic(),"signature":self.signature(nodes),"viewport":viewport,"app":app,"image_signature":image_signature,"nodes":nodes if has_tree else None}
        while len(self.snapshots)>32:
            self.snapshots.popitem(last=False)
        return ident

    def observe(self,mode="tree",include_invisible=False,max_nodes=100,expensive_visibility=False):
        if mode not in ("tree","screenshot","both"):
            fail("invalid_argument","mode must be tree, screenshot or both.")
        integer(max_nodes,"max_nodes",1,500)
        app=self.active_app()
        if mode=="screenshot":
            nodes,viewport=[],self.viewport()
        else:
            nodes,viewport=self.tree(include_invisible,expensive_visibility)
        return self.observation_from_state(nodes,viewport,app,mode,max_nodes,expensive_visibility)

    def observation_from_state(self,nodes,viewport,app,mode,max_nodes=100,expensive_visibility=False):
        result={"observation_id":self.remember(nodes,viewport,app,has_tree=mode!="screenshot"),"observed_at":dt.datetime.now(dt.timezone.utc).isoformat(),"app":app,"viewport":viewport,
                "warnings":["Viewport intersection does not prove hittability; fixed headers can occlude controls."]}
        if mode in ("tree","both"):
            result.update({"nodes":nodes[:max_nodes],"total_nodes":len(nodes),"truncated":len(nodes)>max_nodes,"visibility_computed":expensive_visibility})
            if not nodes:
                result["warnings"].append("Empty accessibility tree: inspect a screenshot for lock, iPhone Mirroring conflict, loading, or custom-rendered content before acting.")
        if mode in ("screenshot","both"):
            encoded=self.client.request("GET","/screenshot").get("value")
            try:
                data=base64.b64decode(encoded,validate=True)
            except (ValueError,TypeError) as exc:
                fail("invalid_response", "Invalid screenshot encoding.")
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                fail("invalid_response","WDA screenshot is not PNG.")
            self.snapshots[result["observation_id"]]["image_signature"]=hashlib.sha256(data).hexdigest()
            artifacts=self.state_dir/"artifacts";artifacts.mkdir(mode=0o700,parents=True,exist_ok=True)
            dest=artifacts/(dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8]+".png")
            dest.write_bytes(data);dest.chmod(0o600)
            for old in sorted(artifacts.glob("*.png"))[:-100]:
                old.unlink()
            result["image"]={"path":str(dest),"mimeType":"image/png","coordinates":"Map image pixels to viewport points before tapping."}
        return result

    def snapshot(self,observation_id):
        old=self.snapshots.get(observation_id)
        if not old:
            stale("This observation is unknown to the current Runtime. Observe again or use current viewport coordinates.","unknown_observation")
        if self.active_app()!=old["app"]:
            stale("The foreground app changed. Observe again.","foreground_changed")
        return old

    def guard(self,observation_id=None):
        old=self.snapshot(observation_id) if observation_id is not None else None
        viewport=self.viewport()
        if old and viewport!=old["viewport"]:
            stale("Orientation or viewport changed. Observe again before using the earlier coordinates.","viewport_changed")
        return viewport

    def guard_region(self,observation_id,region):
        viewport=self.guard(observation_id)
        self.region(region,viewport)
        return viewport

    def find(self,selector,limit=10):
        integer(limit,"limit",1,30)
        found=self.client.session("POST","/elements",{"using":"predicate string","value":predicate(selector)}) or []
        if not isinstance(found,list):
            fail("invalid_response","WDA elements result is not a list.")
        elements=[]
        for item in found[:limit]:
            ident=item.get(ELEMENT_KEY) or item.get("ELEMENT")
            if not isinstance(ident,str):
                continue
            route="/element/"+quote(ident,safe="")
            rect=self.client.session("GET",route+"/rect")
            elements.append({"element_id":ident,"rect":rect})
        return {"elements":elements,"matches":len(found),"truncated":len(found)>limit}

    def target(self,selector,editable=False,found=None,with_kind=False):
        result=found if found is not None else self.find(selector,limit=2)
        if result["matches"]==0:
            fail("no_such_element","Target not found. Read fresh state or use wda_scroll_find.")
        if result["matches"]!=1:
            fail("ambiguous_target","Several elements match. Add exact name/type/value to the selector.",matches=result["matches"])
        element=result["elements"][0]
        rect,viewport=element["rect"],self.viewport()
        cx=rect["x"]+rect["width"]/2;cy=rect["y"]+rect["height"]/2
        if rect["width"]<=0 or rect["height"]<=0 or not (0<=cx<viewport["width"] and 0<=cy<viewport["height"]):
            fail("offscreen_target","Target center is outside the viewport. Scroll the actual list into view, observe again and re-find the target; a stopped batch has not completed its failed step.",action_executed=False,target_rect=rect,viewport=viewport,recovery={"next_tool":"wda_observe","next_arguments":{"mode":"both"},"replay_action":False})
        path="/element/"+quote(element["element_id"],safe="")
        hittable=self.client.session("GET",path+"/attribute/hittable")
        if hittable not in (True,1,"true","1"):
            fail("occluded_target","Target was found but is not hittable; no tap was sent. Inspect the current overlay, picker, fixed header or disabled control before changing the target. Do not assume this failed tap opened a popup, or bypass the check with a coordinate tap.",action_executed=False,target_rect=rect,viewport=viewport,recovery={"next_tool":"wda_observe","next_arguments":{"mode":"both"},"same_target_retry":False,"coordinate_bypass":False,"replay_action":False})
        if editable:
            kind=self.client.session("GET",path+"/attribute/type")
            if kind not in ("XCUIElementTypeTextField","XCUIElementTypeSearchField","XCUIElementTypeTextView"):
                fail("not_editable","Select a readable text/search field or text view. Ask the user to handle secure fields.",secure_field=kind=="XCUIElementTypeSecureTextField")
        if self.screen is not None:
            if len(self._screen_targets)>=32:self._screen_targets.clear()
            self._screen_targets[path]={"x":cx,"y":cy}
        return (path,kind) if editable and with_kind else path

    def wait(self,selector,timeout_seconds=6):
        finite(timeout_seconds,"timeout_seconds",0,20)
        pred=predicate(selector)
        deadline=time.monotonic()+timeout_seconds;attempts=0
        while True:
            attempts+=1
            remaining=max(0.05,deadline-time.monotonic()) if timeout_seconds else 0.5
            found=self.client.session("POST","/elements",{"using":"predicate string","value":pred},timeout=min(remaining,2)) or []
            if found:
                return {"verified":True,"matches":len(found),"polls":attempts,"criterion":"selector exists; presence alone does not prove business success"}
            if time.monotonic()>=deadline:
                fail("postcondition_failed","Expected target did not appear within the wait budget.",polls=attempts)
            time.sleep(min(0.25,max(0,deadline-time.monotonic())))

    def after(self,expect=None,observe="none",max_nodes=100):
        result={"action_executed":True,"action_complete":True,"verified":False,"verification_deferred":True}
        if expect:
            result["postcondition"]=self.wait(expect);result.update(verified=True,verification_deferred=False)
        if observe!="none":
            result["observation"]=self.observe(observe,max_nodes=max_nodes)
        return result

    @action_result
    def tap(self,selector=None,x=None,y=None,observation_id=None,expect=None,observe="none"):
        if observe not in ("none","tree","screenshot","both"):
            fail("invalid_argument","Invalid observation mode.")
        if expect:predicate(expect)
        if selector is not None:
            if x is not None or y is not None:
                fail("invalid_argument","Choose selector or coordinates.")
            path=self.target(selector)
            self.post(path+"/click",{})
        else:
            finite(x,"x");finite(y,"y")
            viewport=self.guard(observation_id)
            if x>=viewport["width"] or y>=viewport["height"]:
                fail("invalid_argument","Coordinates are outside the iPhone viewport.")
            self.post("/wda/tap",{"x":x,"y":y})
        return self.after(expect,observe)

    @action_result
    def launch_app(self,bundle_id,expect=None,observe="none",verify=False):
        if not isinstance(bundle_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+",bundle_id):
            fail("invalid_argument","Use the app's verified bundle ID.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        if not isinstance(verify,bool):fail("invalid_argument","verify must be boolean.")
        if expect:predicate(expect)
        self.post("/wda/apps/activate",{"bundleId":bundle_id},timeout=45)
        if not verify:
            result=self.after(expect,observe);result["foreground_verified"]=False
            return result
        deadline=time.monotonic()+5
        app=None
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                fail("postcondition_failed","Activation was accepted, but the requested app did not become foreground within five seconds. Inspect loading, login or system prompts before continuing; do not replay activation automatically.",requested_app=bundle_id,foreground_app=app,foreground_verified=False,recovery={"next_tool":"wda_observe","next_arguments":{"mode":"both"},"replay_action":False})
            app=self.active_app(timeout=remaining)
            if app==bundle_id:break
            time.sleep(min(.1,max(0,deadline-time.monotonic())))
        result=self.after(expect,observe)
        result.update(verified=True,verification_deferred=False,foreground_verified=True,verification_scope="Requested app is foreground; user task completion is separate.")
        return result

    @action_result
    def press_button(self,name,observe="none",verify=False,expect=None):
        if name not in ("home","volumeup","volumedown"):
            fail("invalid_argument","Supported buttons: home, volumeup, volumedown.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        if not isinstance(verify,bool):fail("invalid_argument","verify must be boolean.")
        if expect:predicate(expect)
        if name!="home":
            self.post("/wda/pressButton",{"name":name})
            return self.after(expect,observe)
        # XCTest pressButton can acknowledge Home without changing foreground.
        # WDA's dedicated endpoint activates the system application instead.
        self.post("/wda/homescreen",{},session=False)
        if not verify:
            result=self.after(expect,observe);result["foreground_verified"]=False
            return result
        deadline=time.monotonic()+2
        app=None
        try:
            while True:
                app=self.active_app(timeout=max(.05,deadline-time.monotonic()))
                if app=="com.apple.springboard":break
                if time.monotonic()>=deadline:
                    fail("postcondition_failed","Home request returned, but SpringBoard did not become foreground. Inspect fresh state; do not loop on the same button.",foreground_app=app)
                time.sleep(min(.1,max(0,deadline-time.monotonic())))
            result=self.after(expect,observe)
            result.update(verified=True,verification_deferred=False,foreground_verified=True,foreground_app=app,verification_scope="Home navigation: SpringBoard is foreground; user task completion is separate.")
            return result
        except WDAError as exc:
            exc.details.update({"action_executed":True,"home_foreground_verified":app=="com.apple.springboard","verification_required":"Home was requested. Inspect fresh state before another action; do not automatically replay."})
            raise

    @action_result
    def type_text(self,selector,text,allow_newlines=False,submit=False,replace=True,observe="none",verify=False,expect=None):
        if not isinstance(text,str) or not 1<=len(text)<=10000 or "\x00" in text:
            fail("invalid_argument","text must have 1..10000 characters without NUL.")
        if ("\n" in text or "\r" in text) and not allow_newlines:
            fail("newline_requires_intent","This text contains line breaks, which can send a message. Use allow_newlines only for an observed multiline editor.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        if not isinstance(verify,bool):fail("invalid_argument","verify must be boolean.")
        if expect:predicate(expect)
        path,kind=self.target(selector,editable=True,with_kind=True)
        if ("\n" in text or "\r" in text) and kind!="XCUIElementTypeTextView":
            fail("newline_unsafe","Line breaks are allowed only for a verified TextView.")
        before=(self.client.session("GET",path+"/attribute/value") or "") if verify and not replace else ""
        self.post(path+"/click",{})
        if replace:
            self.post(path+"/clear",{})
        expected=text if replace else str(before)+text
        self.post(path+"/value",{"text":text,"frequency":30})
        if verify:
            actual=self.client.session("GET",path+"/attribute/value")
            if actual!=expected:
                fail("input_mismatch","Typed text did not round-trip exactly. Do not submit or blindly type it again.",expected_length=len(expected),actual_length=len(str(actual or "")))
        result={"action_executed":True,"action_complete":True,"verified":verify,"verification_deferred":not verify,"exact_readback":verify,"characters":len(text),"submitted":False}
        if submit:
            self.post("/wda/keys",{"value":["\n"]})
            result.update({"submitted":True,"verified":False,"verification_deferred":True,"submission_verified":False,"verification_required":"Check the final submission result before claiming task completion; do not automatically repeat submission."})
        if expect:
            result["postcondition"]=self.wait(expect)
            result.update(verified=True,verification_deferred=False)
            if submit:result.update(submission_verified=True,verification_scope="Expected selector is present; verify the final business outcome before claiming task completion.")
        if observe!="none":result["observation"]=self.observe(observe)
        return result

    def region(self,region,viewport):
        if region is None:
            return {"x":viewport["width"]*.15,"y":viewport["height"]*.25,"width":viewport["width"]*.7,"height":viewport["height"]*.5}
        if not isinstance(region,dict) or set(region)!={"x","y","width","height"}:
            fail("invalid_argument","region must have x/y/width/height in iPhone points.")
        for k,v in region.items():finite(v,k,0 if k in ("x","y") else 1)
        if region["x"]+region["width"]>viewport["width"] or region["y"]+region["height"]>viewport["height"]:
            fail("invalid_argument","Gesture region is outside viewport.")
        return region

    def native_modals(self,nodes):
        return [{k:n[k] for k in ("type","name","label","rect") if k in n} for n in nodes if n["type"] in ("XCUIElementTypeAlert","XCUIElementTypeSheet")]

    def scroll_observation(self,nodes,viewport,mode,max_nodes=100):
        if mode=="none":return None
        # The caller already read the complete tree and viewport. Reuse both;
        # adding a screenshot does not require another viewport/XML request.
        return self.observation_from_state(nodes,viewport,self.active_app(),mode,max_nodes)

    def scroll_progress(self,before,after,region,direction):
        # Numeric/value refreshes and animation metadata are not movement.
        # Match unique stable row/text anchors and require a displacement along
        # the requested axis, with substantially unchanged row dimensions.
        def anchors(nodes):
            found=collections.defaultdict(list)
            for node in self.region_nodes(nodes,region):
                if node["type"] not in ("XCUIElementTypeCell","XCUIElementTypeStaticText","XCUIElementTypeOther","XCUIElementTypeImage"):
                    continue
                for field in ("name","label"):
                    value=node.get(field)
                    if isinstance(value,str) and value:
                        found[(node["type"],field,value)].append(node["rect"])
            return {key:rects[0] for key,rects in found.items() if len(rects)==1}
        old,new=anchors(before),anchors(after)
        axis,cross=("y","x") if direction in ("up","down") else ("x","y")
        sign=-1 if direction in ("up","left") else 1
        for key in old.keys()&new.keys():
            a,b=old[key],new[key]
            if (b[axis]-a[axis])*sign>2 and abs(b[cross]-a[cross])<=3 and all(abs(b[k]-a[k])<=2 for k in ("width","height")):
                return True
        return False

    @action_result
    def swipe(self,direction="up",region=None,observation_id=None,expect=None,verify=False,max_attempts=2,observe="none",_baseline=None,_max_nodes=100):
        if direction not in ("up","down","left","right"):fail("invalid_argument","Invalid direction.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        integer(max_attempts,"max_attempts",1,2)
        if not isinstance(verify,bool):fail("invalid_argument","verify must be boolean.")
        if expect:predicate(expect)
        viewport=self.guard_region(observation_id,region) if observation_id is not None else None
        if verify:
            before,current_viewport=_baseline if _baseline is not None else self.tree()
            if viewport is not None and current_viewport!=viewport:
                stale("Viewport changed while preparing this scroll.","viewport_changed","region")
            viewport=current_viewport
        else:
            before=[]
            if viewport is None:viewport=_baseline[1] if _baseline is not None else self.viewport()
        area=self.region(region,viewport)
        modals=self.native_modals(before) if verify else []
        if modals:
            contained=lambda m:area["x"]>=m["rect"]["x"] and area["y"]>=m["rect"]["y"] and area["x"]+area["width"]<=m["rect"]["x"]+m["rect"]["width"] and area["y"]+area["height"]<=m["rect"]["y"]+m["rect"]["height"]
            if region is None or not all(contained(m) for m in modals):
                details={"action_executed":False,"verified":False,"region":area,"native_modals":modals,"recovery":{"next_tool":"wda_observe","next_arguments":{"mode":"both"},"replay_action":False,"next_step":"Handle the existing modal first, or choose a fresh explicit scroll region wholly inside its intended list. Do not scroll the underlying page through a modal."}}
                observed=self.scroll_observation(before,viewport,observe,_max_nodes)
                if observed:details["observation"]=observed
                fail("modal_requires_region" if region is None else "blocked_scroll_region","Native modals are present. The intended scroll area must be explicit and inside every modal's bounds; otherwise handle the foreground modal first.",**details)
        x=area["x"]+area["width"]/2;y=area["y"]+area["height"]/2
        dx=area["width"]*.32;dy=area["height"]*.32
        points={"up":(x,y+dy,x,y-dy),"down":(x,y-dy,x,y+dy),"left":(x+dx,y,x-dx,y),"right":(x-dx,y,x+dx,y)}[direction]
        for attempt in range(max_attempts if verify else 1):
            strategy="short_drag" if attempt==0 else "native_swipe"
            if attempt==0:
                self.post("/wda/dragfromtoforduration",dict(zip(("fromX","fromY","toX","toY"),points),duration=.1))
            else:
                self.screen_event("drag",**{"from_point":{"x":points[0],"y":points[1]},"to_point":{"x":points[2],"y":points[3]},"duration_ms":450})
                self.post("/wda/swipe",{"direction":direction,"x":x,"y":y},timeout=20)
            if not verify:
                result=self.after(expect,observe,max_nodes=_max_nodes)
                result.update(strategy=strategy,attempts=1,progress_verified=False)
                return result
            after,v=self.tree()
            reasons=[]
            if v!=viewport:reasons.append("viewport_changed")
            if self.native_modals(after)!=modals:reasons.append("modal_changed")
            if reasons:
                details={"action_executed":True,"verified":False,"changed":False,"attempts":attempt+1,"reasons":reasons,"recovery":{"next_tool":"wda_observe","next_arguments":{"mode":"both"},"same_gesture_retry":False,"replay_action":False,"next_step":"Inspect the changed viewport/modal and choose the current target; do not continue a fallback gesture against the old page."}}
                observed=self.scroll_observation(after,v,observe,_max_nodes)
                if observed:details["observation"]=observed
                fail("scroll_context_changed","A gesture was accepted, but the viewport or native modal context changed. This is not verified list progress; the fallback gesture was stopped.",**details)
            changed=self.scroll_progress(before,after,area,direction)
            if changed:
                result={"action_executed":True,"action_complete":True,"verified":True,"verification_deferred":False,"changed":True,"progress_verified":True,"verification_scope":"Stable accessibility anchors moved in the requested direction; business coverage is separate.", "attempts":attempt+1,"strategy":strategy}
                observed=self.scroll_observation(after,v,observe,_max_nodes)
                if observed:result["observation"]=observed
                if expect:result["postcondition"]=self.wait(expect)
                return result
        details={"action_executed":True,"verified":False,"changed":False,"attempts":max_attempts,"region":area,
                 "recovery":{"next_tool":"wda_observe","next_arguments":{"mode":"both"},"next_step":"Inspect the current page and list entrance. If this is an overview, tap the actual list entry; if at the end, reconcile counts. Otherwise inspect a screenshot, including custom pickers/overlays that may not appear as native modals, or another stable region.","same_gesture_retry":False,"end_of_list_proven":False}}
        observed=self.scroll_observation(after,v,observe,_max_nodes)
        if observed:details["observation"]=observed
        fail("no_scroll_progress","Gestures executed but stable accessibility anchors did not show movement in the requested direction. The page may be an overview, boundary, blocked region or custom-rendered list. Changing numbers alone are not scroll progress. This does not prove an empty or complete list; inspect returned state before choosing the next action.",**details)

    @action_result
    def scroll_find(self,selector,direction="up",max_swipes=6):
        predicate(selector);integer(max_swipes,"max_swipes",0,10)
        for count in range(max_swipes+1):
            found=self.find(selector,limit=2)
            if found["matches"]==1:
                try:
                    self.target(selector,found=found)
                    return {"verified":True,"swipes":count,**found}
                except WDAError as exc:
                    if exc.code not in ("offscreen_target","occluded_target"):raise
            elif found["matches"]>1:
                fail("ambiguous_target","Several targets match while scrolling. Refine selector.")
            if count==max_swipes:break
            self.swipe(direction,verify=False,observe="none")
        fail("search_exhausted","Target did not become hittable within max_swipes.",swipes=max_swipes)

    @action_result
    def collect_list(self,row_type="Cell",max_pages=6,end_selector=None):
        integer(max_pages,"max_pages",1,10)
        if end_selector:predicate(end_selector)
        if not isinstance(row_type,str) or not re.fullmatch(r"(?:XCUIElementType)?[A-Za-z]+",row_type):fail("invalid_argument","Invalid row_type.")
        kind=row_type if row_type.startswith("XCUIElementType") else "XCUIElementType"+row_type
        rows={};pages=[];seen_pages=set();reason="page_budget";end=False
        observed=self.observe(max_nodes=500)
        for index in range(max_pages):
            nodes=self.snapshots[observed["observation_id"]]["nodes"]
            current=[n for n in nodes if n["type"]==kind]
            for n in current:
                key=json.dumps({k:n[k] for k in ("type","name","label","value") if k in n},ensure_ascii=False,sort_keys=True)
                rows.setdefault(key,n)
            pages.append({"page":index+1,"rows_seen":len(current),"truncated":observed["truncated"]})
            found=self.find(end_selector,limit=2) if end_selector else None
            if found and found["matches"]:
                try:self.target(end_selector,found=found);end=True;reason="explicit_end_marker";break
                except WDAError as exc:
                    if exc.code not in ("offscreen_target","occluded_target","ambiguous_target"):raise
            # Collection already needs the next page, so consume it directly.
            # Virtualized lists may replace every label in fixed row slots;
            # requiring a shared moving anchor would discard that new page.
            # Ignore value refreshes and unrelated controls for repeat detection.
            page_key=json.dumps([{k:n[k] for k in ("type","name","label","rect") if k in n} for n in current],ensure_ascii=False,sort_keys=True)
            if page_key in seen_pages:
                reason="no_progress";break
            seen_pages.add(page_key)
            if index==max_pages-1:break
            observed=self.swipe("up",verify=False,observe="tree",_baseline=(nodes,observed["viewport"]),_max_nodes=500)["observation"]
        return {"rows":list(rows.values()),"pages":pages,"stop_reason":reason,"end_marker_seen":end,"complete":False,
                "coverage_verified":end and not any(p["truncated"] for p in pages),
                "limitations":["Rows deduplicate by identical type/name/label/value; identical rows may collapse.","Only exposed accessibility labels are collected. Reconcile expected counts, screenshot-only fields, totals, currencies and dates before claiming business completeness."]}

    def batch(self,steps):
        if not isinstance(steps,list) or not 1<=len(steps)<=20:
            fail("invalid_argument","steps must contain 1..20 operations.")
        allowed={"tap":self.tap,"swipe":self.swipe,"type_text":self.type_text,"launch_app":self.launch_app,"press_button":self.press_button,"wait":self.wait,"observe":self.observe,"scroll_find":self.scroll_find}
        # Validate every step's shape before executing anything. Tool schemas validate nested arguments in the MCP layer.
        for step in steps:
            if not isinstance(step,dict) or set(step)-{"op","args"} or step.get("op") not in allowed or not isinstance(step.get("args",{}),dict):
                fail("invalid_argument","Each batch step needs a supported op and args object.")
        results=[]
        for index,step in enumerate(steps):
            try:
                result=allowed[step["op"]](**step.get("args",{}));results.append(result)
                if result.get("submitted") and not result.get("submission_verified"):
                    return {"completed_steps":len(results),"stopped_at":index,"stop_reason":"submission_requires_verification","results":results,"complete":False}
            except WDAError as exc:
                return {"completed_steps":len(results),"stopped_at":index,"stop_reason":exc.code,"error":exc.as_dict(),"results":results,"complete":False}
        return {"completed_steps":len(results),"results":results,"complete":True}
