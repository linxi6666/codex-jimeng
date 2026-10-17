'use strict';
// User-authorized direct requests in the dedicated Chrome's existing login.
// Cookies remain in Chrome. Temporary upload credentials remain in RAM only.
const fs=require('node:fs');
const crypto=require('node:crypto');
const API_ORIGIN='https://jimeng.jianying.com';
const ROUTES=new Set(['/octo_api/v1/resource/upload','/mweb/v1/dreamina_subject/get','/mweb/v1/dreamina_subject/create','/mweb/v1/get_upload_token','/mweb/v1/get_image_by_uri','/mweb/v1/imagex/submit_audit_job']);
class ChromeAPI {
  constructor(){this.seq=0;this.pending=new Map();}
  async connect(){
    const v=await fetch('http://127.0.0.1:9227/json/version',{signal:AbortSignal.timeout(3000)}).then(r=>r.json());
    const url=new URL(v.webSocketDebuggerUrl);if(url.hostname!=='127.0.0.1'||url.protocol!=='ws:')throw new Error('Unexpected debugging host');
    this.ws=new WebSocket(url);await new Promise((resolve,reject)=>{this.ws.addEventListener('open',resolve,{once:true});this.ws.addEventListener('error',()=>reject(new Error('Chrome connection failed')),{once:true});});
    this.ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=this.pending.get(m.id);if(p){clearTimeout(p.timer);this.pending.delete(m.id);m.error?p.reject(new Error('Chrome command failed')):p.resolve(m.result);}}});
    const {targetInfos}=await this.send('Target.getTargets');
    const pages=targetInfos.filter(t=>t.type==='page'&&/^https:\/\/jimeng\.jianying\.com\//.test(t.url));
    if(pages.length!==1)throw new Error('Keep exactly one Jimeng tab in the dedicated Chrome');
    this.session=(await this.send('Target.attachToTarget',{targetId:pages[0].targetId,flatten:true})).sessionId;
    return this;
  }
  send(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++this.seq;
    const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('Chrome command timed out'));},60000);
    this.pending.set(id,{resolve,reject,timer});this.ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});}
  async post(route,data){
    if(!ROUTES.has(route))throw new Error('API route is not allowed');
    const expression=`(async()=>{const response=await fetch(${JSON.stringify(API_ORIGIN+route+'?aid=513695')},{method:'POST',credentials:'include',headers:{'content-type':'application/json','accept':'application/json'},body:${JSON.stringify(JSON.stringify(data))}});return {status:response.status,body:await response.json()};})()`;
    const r=await this.send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},this.session);
    if(r.exceptionDetails)throw new Error('API request failed in Chrome');
    return r.result.value;
  }
  close(){for(const p of this.pending.values())clearTimeout(p.timer);this.ws?.close();}
}
async function main(){
  const c=new ChromeAPI();
  try{
    await c.connect();
    const result=await c.post('/mweb/v1/dreamina_subject/get',{cursor:0,limit:20});
    console.log(JSON.stringify({route:'/mweb/v1/dreamina_subject/get',status:result.status,ret:result.body.ret,bodyKeys:Object.keys(result.body),dataKeys:Object.keys(result.body.data||{}),subjects:result.body.data?.data_list?.map(s=>({name:s.content?.name,subjectId:s.subject_id})),hasMore:result.body.data?.has_more}));
  }finally{c.close();}
}
if(require.main===module)main().catch(()=>{console.error('Direct API probe failed; no credentials or raw response logged.');process.exitCode=1;});
module.exports={ChromeAPI,ROUTES};
