'use strict';
// Passive CDP listener for the user-approved dedicated Chrome profile.
// No request replay, browser clicking, credential extraction, or system proxy.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');

const SECRET = /cookie|token|signature|authorization|password|passwd|secret|credential|session|captcha|verify_code|phone|email|user_id|account_id|device_id|fingerprint|msToken|a_bogus|x_bogus|policy|signed|upload_id|storage_key|(^|_)uri($|_)/i;
const SAFE_VALUES = new Set(['type','sub_type','scene','biz','action','source','status','code','version','app_id','aid','app_version','model','model_name','resolution','duration','ratio','count','offset','limit','page','page_size','resource_type','media_type','source_type','entry_type','format','success']);
const LOGIN = /passport|oauth|login|logout|captcha|send_sms|verify_sms|auth\/|\/auth$|\/account(?:\/|$)/i;
const TELEMETRY = /\/monitor|\/report|\/track|\/log(?:\/|$)|\/collect(?:\/|$)/i;
function digest(value){return crypto.createHash('sha256').update(String(value)).digest('hex').slice(0,12);}
function routePath(value){
  return value.split('/').map(p=>/^[0-9]{6,}$/.test(p)||/^[a-f0-9-]{24,}$/i.test(p)||p.length>70?'[opaque]':p).join('/');
}
function redact(value,key='',depth=0){
  if(SECRET.test(key))return '[redacted]';
  if(depth>9)return '[depth-limit]';
  if(Array.isArray(value))return value.slice(0,8).map(v=>redact(v,key,depth+1));
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).slice(0,120).map(([k,v])=>[k,redact(v,k,depth+1)]));
  if(value===null||typeof value==='boolean')return value;
  if(typeof value==='number')return SAFE_VALUES.has(key)?value:'[number]';
  if(typeof value==='string'){
    if(/^https?:\/\//i.test(value))return '[url]';
    if(SAFE_VALUES.has(key)&&value.length<100&&!/[\r\n]/.test(value)&&!/[A-Za-z0-9+/_=-]{40,}/.test(value))return value;
    if(/(^|_)id$|_ids$|^id$|^ids$/i.test(key))return '[id:'+digest(value)+']';
    return value===''?'':'[string]';
  }
  return '[unknown]';
}
function safeBody(text,contentType=''){
  if(!text)return null;
  if(text.length>1024*1024)return {omitted:'body over 1MiB'};
  try{return redact(JSON.parse(text));}catch{}
  if(contentType.includes('application/x-www-form-urlencoded')){
    return redact(Object.fromEntries(new URLSearchParams(text)));
  }
  return {omitted:'non-json or binary body',length:text.length};
}
function allowedHost(host){
  return host==='jimeng.jianying.com'||['volces.com','bytedance.com','byteimg.com','bytedanceapi.com','snssdk.com','pstatp.com','vlabvod.com'].some(d=>host===d||host.endsWith('.'+d));
}
function eligible(url,type,method){
  try{const u=new URL(url);return u.protocol==='https:'&&allowedHost(u.hostname)&&!LOGIN.test(u.pathname)&&!TELEMETRY.test(u.pathname)&&
    (['XHR','Fetch'].includes(type)||['POST','PUT','PATCH','DELETE'].includes(method));}catch{return false;}
}
function safeUrl(value){
  const u=new URL(value);const query={};
  for(const [k,v] of u.searchParams){query[k]=redact(v,k);}
  return {origin:u.origin,path:routePath(u.pathname),query};
}
function safeHeaderTypes(headers){
  const result={};for(const [k,v] of Object.entries(headers||{})){
    if(['content-type','accept'].includes(k.toLowerCase()))result[k.toLowerCase()]=String(v).split(';')[0].slice(0,100);
  }return result;
}

async function main(){
  const port=Number(process.env.JIMENG_DEBUG_PORT||9227);
  const statusPort=Number(process.env.JIMENG_CAPTURE_PORT||9230);
  const directory=path.join(__dirname,'.data','network-capture');fs.mkdirSync(directory,{recursive:true});
  const output=path.join(directory,'requests.jsonl');
  const status={running:true,connected:false,attachedPages:0,capturedThisRun:0,lastCapture:null,error:null,debugPort:port,output};
  const sessions=new Map(),requests=new Map(),pending=new Map();let seq=0,ws=null;
  function write(record){
    fs.appendFileSync(output,JSON.stringify(record)+'\n',{encoding:'utf8',mode:0o600});
    status.capturedThisRun++;status.lastCapture={time:record.time,method:record.method,origin:record.url.origin,path:record.url.path,status:record.response?.status};
    // Neither query strings, body values, nor headers enter terminal output.
    console.log(`[capture] ${record.method} ${record.url.origin}${record.url.path} ${record.response?.status||'pending'}`);
  }
  function send(method,params={},sessionId){
    return new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP command timed out'));},15000);pending.set(id,{resolve,reject,timer});
      ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
  }
  async function attach(info){
    if(info.type!=='page'||![...sessions.values()].every(s=>s.targetId!==info.targetId))return;
    const {sessionId}=await send('Target.attachToTarget',{targetId:info.targetId,flatten:true});
    sessions.set(sessionId,{targetId:info.targetId,url:info.url});status.attachedPages=sessions.size;
    await send('Network.enable',{maxTotalBufferSize:8*1024*1024,maxResourceBufferSize:1024*1024},sessionId);
  }
  async function finish(sessionId,id,failure){
    const key=sessionId+':'+id,item=requests.get(key);if(!item)return;requests.delete(key);
    if(!failure&&item.response?.mimeType?.includes('json')&&item.size<=1024*1024){
      try{const body=await send('Network.getResponseBody',{requestId:id},sessionId);if(!body.base64Encoded)item.record.responseBody=safeBody(body.body,item.response.mimeType);}catch{item.record.responseBody={omitted:'not available'};}
    }
    if(failure)item.record.failure='network-failed';
    write(item.record);
  }
  const server=http.createServer((req,res)=>{
    if(!['127.0.0.1:'+statusPort,'localhost:'+statusPort].includes(req.headers.host)||req.method!=='GET'||req.url!=='/status'){
      res.writeHead(404);return res.end();}
    res.writeHead(200,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(status));
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(statusPort,'127.0.0.1',resolve);});
  async function connect(){
    try{
      const version=await fetch(`http://127.0.0.1:${port}/json/version`,{signal:AbortSignal.timeout(3000)}).then(r=>r.json());
      const url=new URL(version.webSocketDebuggerUrl);if(url.hostname!=='127.0.0.1'||url.protocol!=='ws:')throw new Error('Unexpected debugging address');
      ws=new WebSocket(url);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
      status.connected=true;status.error=null;
      ws.addEventListener('message',event=>{
        (async()=>{
          const m=JSON.parse(event.data);
          if(m.id){const p=pending.get(m.id);if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(new Error('CDP command rejected')):p.resolve(m.result);}return;}
          const p=m.params||{},sid=m.sessionId;
          if(m.method==='Target.targetCreated'){await attach(p.targetInfo);return;}
          if(m.method==='Target.targetInfoChanged'){for(const s of sessions.values())if(s.targetId===p.targetInfo.targetId)s.url=p.targetInfo.url;return;}
          if(m.method==='Target.detachedFromTarget'){sessions.delete(p.sessionId);status.attachedPages=sessions.size;return;}
          const page=sessions.get(sid);if(!page)return;
          let official=false;try{official=new URL(page.url).hostname==='jimeng.jianying.com';}catch{}
          if(!official)return;
          const key=sid+':'+p.requestId;
          if(m.method==='Network.requestWillBeSent'&&eligible(p.request.url,p.type,p.request.method)){
            const r=p.request;
            requests.set(key,{time:Date.now(),record:{time:new Date().toISOString(),method:r.method,type:p.type,url:safeUrl(r.url),headers:safeHeaderTypes(r.headers),requestBody:safeBody(r.postData,Object.entries(r.headers||{}).find(([k])=>k.toLowerCase()==='content-type')?.[1]||'')},size:0});
          }else if(m.method==='Network.responseReceived'&&requests.has(key)){
            const item=requests.get(key);item.response=p.response;item.record.response={status:p.response.status,mimeType:p.response.mimeType};
          }else if(m.method==='Network.loadingFinished'&&requests.has(key)){
            requests.get(key).size=p.encodedDataLength;await finish(sid,p.requestId,false);
          }else if(m.method==='Network.loadingFailed'){await finish(sid,p.requestId,true);}
        })().catch(()=>{status.error='A capture event could not be processed; no raw data was logged.';});
      });
      ws.addEventListener('close',()=>{status.connected=false;sessions.clear();status.attachedPages=0;requests.clear();setTimeout(connect,3000);});
      await send('Target.setDiscoverTargets',{discover:true});
      const {targetInfos}=await send('Target.getTargets');for(const info of targetInfos)await attach(info);
      console.log('Jimeng passive capture ready. Sensitive fields are redacted before disk writes.');
    }catch{status.connected=false;status.error='Waiting for the dedicated Chrome debugging port';setTimeout(connect,3000);}
  }
  // Drop incomplete metadata after five minutes. No credentials are retained.
  setInterval(()=>{for(const [key,item] of requests)if(Date.now()-item.time>300000)requests.delete(key);},60000).unref();
  console.log(`Local capture status: http://127.0.0.1:${statusPort}/status`);
  await connect();
  function stop(){status.running=false;for(const p of pending.values())clearTimeout(p.timer);ws?.close();server.close();process.exit(0);}
  process.on('SIGINT',stop);process.on('SIGTERM',stop);
}
if(require.main===module)main().catch(()=>{console.error('Capture startup failed. Check local ports.');process.exitCode=1;});
module.exports={redact,safeBody,safeUrl,eligible,safeHeaderTypes};
