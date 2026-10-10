"""Loopback OneBot simulator. Synthetic identities only; never real QQ proof."""
import asyncio
import json
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import time
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed


class OneBotFixture:
    def __init__(self):
        self.token=secrets.token_hex(32)
        self.clients=set();self.calls=[];self.sends=[];self.reject=False;self.auth=False;self.redirect=False
        self.server=self.ws=self.thread=None
    async def __aenter__(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if owner.redirect:
                    self.send_response(302);self.send_header('Location','http://127.0.0.1:1/never');self.end_headers();return
                if owner.auth or self.headers.get('Authorization')!='Bearer '+owner.token:
                    self.send_response(401);self.end_headers();return
                params=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(self.path)
                data={'user_id':99,'nickname':'isolated fixture'}
                if self.path in ('/send_private_msg','/send_group_msg'):
                    owner.sends.append((self.path,params))
                    data={'message_id':800+len(owner.sends)}
                payload={'status':'failed' if owner.reject else 'ok','retcode':100 if owner.reject else 0,'data':data}
                raw=json.dumps(payload).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*args): pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        async def process_request(connection,request):
            if request.headers.get('Authorization')!='Bearer '+self.token:
                return connection.respond(HTTPStatus.UNAUTHORIZED,'Unauthorized')
        async def handler(connection):
            self.clients.add(connection)
            try:
                async for raw in connection:
                    p=json.loads(raw);action=p.get('action');params=p.get('params',{})
                    self.calls.append(action)
                    data={'user_id':99,'nickname':'isolated fixture'}
                    if action in ('send_private_msg','send_group_msg'):
                        self.sends.append((action,params));data={'message_id':800+len(self.sends)}
                    await connection.send(json.dumps({'status':'failed' if self.reject else 'ok',
                        'retcode':100 if self.reject else 0,'data':data,'echo':p.get('echo')}))
            finally:self.clients.discard(connection)
        self.ws=await serve(handler,'127.0.0.1',0,process_request=process_request)
        self.http_url=f'http://127.0.0.1:{self.server.server_port}'
        self.ws_url=f'ws://127.0.0.1:{self.ws.sockets[0].getsockname()[1]}'
        return self
    async def publish(self, sender=7, group=None, message_id=1, text='isolated test input', mention=True):
        e={'post_type':'message','message_type':'group' if group else 'private','self_id':99,'user_id':sender,
           'sender':{'user_id':sender},'message_id':message_id,'time':int(time()),
           'message':([{'type':'at','data':{'qq':'99'}}] if group and mention else [])+[{'type':'text','data':{'text':text}}]}
        if group:e['group_id']=group
        for client in tuple(self.clients):
            try:await client.send(json.dumps(e))
            except ConnectionClosed:self.clients.discard(client)
    async def __aexit__(self,*args):
        self.ws.close();await self.ws.wait_closed()
        await asyncio.to_thread(self.server.shutdown);self.server.server_close();self.thread.join(2)


async def desktop_fixture():
    # Private stdin/stdout handoff for an owned test process. Never log token.
    async with OneBotFixture() as fixture:
        print(json.dumps({'http':fixture.http_url,'ws':fixture.ws_url,'token':fixture.token}),flush=True)
        import sys
        while True:
            raw=await asyncio.to_thread(sys.stdin.readline)
            if not raw:break
            p=json.loads(raw)
            if p['action']=='exit':break
            if p['action']=='publish':await fixture.publish(**p.get('params',{}))
            if p['action']=='close':
                for c in tuple(fixture.clients):await c.close()
            print(json.dumps({'clients':len(fixture.clients),'sends':len(fixture.sends),'calls':fixture.calls}),flush=True)

if __name__=='__main__':
    import sys
    sys.stdin.reconfigure(encoding='utf-8', errors='strict')
    sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    asyncio.run(desktop_fixture())
