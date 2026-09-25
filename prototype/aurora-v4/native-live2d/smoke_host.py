"""Opt-in real native host gate, read-only external SDK/model inputs."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import struct
import zlib


def surface_info(path):
    """Read the adapter's non-interlaced RGBA8 PNG without a test dependency."""
    data=path.read_bytes();assert data[:8]==b'\x89PNG\r\n\x1a\n'
    width,height,bits,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',data[16:29])
    assert (bits,color,compression,filtering,interlace)==(8,6,0,0,0)
    chunks=[];offset=8
    while offset<len(data):
        size=struct.unpack('>I',data[offset:offset+4])[0];kind=data[offset+4:offset+8]
        if kind==b'IDAT':chunks.append(data[offset+8:offset+8+size])
        offset+=size+12
    decoded=zlib.decompress(b''.join(chunks));stride=width*4;previous=bytearray(stride);alpha=[]
    for y in range(height):
        start=y*(stride+1);mode=decoded[start];row=bytearray(decoded[start+1:start+stride+1])
        assert mode in range(5)
        for x in range(stride):
            a=row[x-4] if x>=4 else 0;b=previous[x];c=previous[x-4] if x>=4 else 0
            p=a+b-c;distances=(abs(p-a),abs(p-b),abs(p-c));paeth=(a,b,c)[distances.index(min(distances))]
            row[x]=(row[x]+(0,a,b,(a+b)//2,paeth)[mode])&255
        alpha.extend(row[3::4]);previous=row
    assert min(alpha)==0 and max(alpha)>0,'Surface must have real model pixels and transparency'
    return {'size':[width,height],'alpha_range':[min(alpha),max(alpha)],'model_pixels':sum(a>0 for a in alpha)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--shaders',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'AURORA_LIVE2D_MODEL':str(args.model.resolve()),
         'AURORA_LIVE2D_SHADERS':str(args.shaders.resolve()),
         'AURORA_LIVE2D_CAPTURE_PATH':str((args.output/'frame.png').resolve())}
    child=subprocess.Popen([str(args.host.resolve())],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    events=queue.Queue(maxsize=128)
    def receive():
        for line in child.stdout:
            try:events.put_nowait(json.loads(line))
            except (ValueError,queue.Full):pass
    reader=threading.Thread(target=receive);reader.start()
    report={'status':'failed','events':[],'manual':'NOT MANUALLY VERIFIED'}
    def event(kind,timeout=30):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:e=events.get(timeout=.2)
            except queue.Empty:
                if child.poll() is not None:raise RuntimeError('Host exited before expected event')
                continue
            report['events'].append(e)
            if e['type']=='error':raise RuntimeError(e['code'])
            if e['type']==kind:return e
        raise TimeoutError(kind)
    def send(revision,state='idle',visible=True,shutdown=False):
        child.stdin.write(json.dumps(dict(revision=revision,state=state,visible=visible,x=None,y=None,shutdown=shutdown))+'\n');child.stdin.flush()
    try:
        event('ready');send(1)
        for rev,state,visible in [(1,'idle',True),(2,'thinking',True),(3,'speaking',True),(4,'idle',False),(5,'idle',True)]:
            send(rev,state,visible)
            while True:
                value=event('metrics')
                if value['revision']==rev:break
            assert value['state']==state and value['visible']==visible
            # First sample can include initial hidden frames, subsequent full
            # interval must render if visible, and must not render if hidden.
            value=event('metrics')
            assert value['frames']>0 if visible else value['frames']==0
            assert value['frames']/value['seconds']<=61
        send(6,shutdown=True);event('closed');assert child.wait(10)==0
        report['surface']=surface_info(args.output/'frame.png')
        report['status']='passed'
    finally:
        if child.poll() is None:
            child.stdin.close()
            try:child.wait(5)
            except subprocess.TimeoutExpired:child.kill();child.wait(5)
        reader.join(5)
        report['reader_alive']=reader.is_alive();report['exit_code']=child.returncode
        report['stderr']=child.stderr.read()[-2000:]
        (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))


if __name__=='__main__':main()
