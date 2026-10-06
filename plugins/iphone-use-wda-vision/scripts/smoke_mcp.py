#!/usr/bin/env python3
"""Read-only MCP smoke check through a real stdio process. No screenshot contents printed."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--ready',action='store_true',help='Verify an already-running real WDA; reads phone state and screenshot without XML.');args=parser.parse_args()
    child=subprocess.Popen([sys.executable,str(ROOT/'server/iphone_wda.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,text=True)
    counter=0;records=[]
    def rpc(method,params):
        nonlocal counter
        counter+=1;started=time.monotonic()
        child.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':method,'params':params})+'\n');child.stdin.flush()
        response=json.loads(child.stdout.readline())
        assert response['id']==counter and 'error' not in response,response.get('error')
        records.append({'method':method,'seconds':round(time.monotonic()-started,3)})
        return response['result']
    try:
        init=rpc('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'iphone-wda-vision-smoke','version':'1.0'}})
        child.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');child.stdin.flush()
        catalog=rpc('tools/list',{})
        rpc('ping',{})
        result={'server':init['serverInfo'],'tools':len(catalog['tools']),'protocol_ok':True}
        if args.ready:
            ready=rpc('tools/call',{'name':'wda_vision_ready','arguments':{'recover':False}})
            if ready.get('isError'):
                print(json.dumps({'ready':False,'error':ready['structuredContent'].get('error')},ensure_ascii=False));return 1
            data=ready['structuredContent']
            if data.get('ready') is not True:
                print(json.dumps({'server':result['server'],'tools':result['tools'],'protocol_ok':True,**data},ensure_ascii=False));return 1
            result['ready']=True;result['proof']=data['proof']
            result['image_content_returned']=any(c['type']=='image' for c in ready['content'])
        result['timings']=records;print(json.dumps(result,ensure_ascii=False));return 0
    finally:
        child.stdin.close()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=3)
        child.stdout.close()


if __name__=='__main__':sys.exit(main())
