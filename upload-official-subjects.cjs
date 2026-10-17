'use strict';
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {ChromeAPI}=require('./jimeng-direct.cjs');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const hmac=(key,text)=>crypto.createHmac('sha256',key).update(text).digest();
const escape=s=>encodeURIComponent(s).replace(/[!'()*]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase());
function signImageX(method,query,body,credential,now=new Date()){
  const host='imagex.bytedanceapi.com',region='cn-north-1',service='imagex';
  const date=now.toISOString().replace(/[:-]|\.\d{3}/g,''),day=date.slice(0,8);
  const queryString=Object.keys(query).sort().map(k=>escape(k)+'='+escape(String(query[k]))).join('&');
  const headers={'x-amz-date':date,'x-amz-security-token':credential.session_token};
  if(body)headers['x-amz-content-sha256']=sha(body);
  const signedHeaders=Object.keys(headers).sort().join(';');
  const canonicalHeaders=Object.keys(headers).sort().map(k=>k+':'+String(headers[k]).trim().replace(/\s+/g,' ')).join('\n');
  const canonical=[method,'/',queryString,canonicalHeaders+'\n',signedHeaders,sha(body||'')].join('\n');
  const scope=[day,region,service,'aws4_request'].join('/');
  const signingKey=hmac(hmac(hmac(hmac('AWS4'+credential.secret_access_key,day),region),service),'aws4_request');
  const signature=hmac(signingKey,['AWS4-HMAC-SHA256',date,scope,sha(canonical)].join('\n')).toString('hex');
  headers.authorization=`AWS4-HMAC-SHA256 Credential=${credential.access_key_id}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  if(body)headers['content-type']='application/json';
  return {url:'https://'+host+'/?'+queryString,headers};
}
function crc32(b){let crc=0xffffffff;for(const n of b){crc^=n;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return ((crc^0xffffffff)>>>0).toString(16).padStart(8,'0');}
function pngSize(b){if(b.length<24||b.subarray(0,8).toString('hex')!=='89504e470d0a1a0a')throw new Error('Sample uploader currently requires PNG');return {width:b.readUInt32BE(16),height:b.readUInt32BE(20)};}
function imageSize(b){
  if(b.subarray(0,8).toString('hex')==='89504e470d0a1a0a')return pngSize(b);
  if(b.length>=4&&b[0]===0xff&&b[1]===0xd8){
    let i=2;
    while(i+3<b.length){
      if(b[i++]!==0xff)continue;
      while(b[i]===0xff)i++;
      const marker=b[i++];if(marker===0xd9||marker===0xda)break;
      if(marker===0x01||(marker>=0xd0&&marker<=0xd8))continue;
      const length=b.readUInt16BE(i);if(length<2||i+length>b.length)break;
      if([0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf].includes(marker)&&length>=7)return {width:b.readUInt16BE(i+5),height:b.readUInt16BE(i+3)};
      i+=length;
    }
  }
  throw new Error('Unsupported or corrupt image (PNG/JPEG required)');
}
async function imageX(action,query,body,credential){
  const method=body?'POST':'GET',text=body?JSON.stringify(body):'';
  const signed=signImageX(method,{Action:action,Version:'2018-08-01',ServiceId:credential.space_name,...query},text,credential);
  let response;try{response=await fetch(signed.url,{method,headers:signed.headers,...(body?{body:text}:{}),redirect:'error',signal:AbortSignal.timeout(60000)});}catch{throw new Error(action+' network failed; stopped without retry');}
  let j;try{j=await response.json();}catch{throw new Error(action+' returned non-JSON');}
  const error=j.ResponseMetadata?.Error;
  if(!response.ok||error)throw new Error(action+' rejected: HTTP '+response.status+' code '+String(error?.Code||'unknown').replace(/[^A-Za-z0-9_.-]/g,''));
  if(!j.Result)throw new Error(action+' response missing Result');return j.Result;
}
async function api(c,route,body){
  const r=await c.post(route,body);
  if(r.status!==200||String(r.body.ret)!=='0')throw new Error(route+' rejected: HTTP '+r.status+' ret '+String(r.body.ret).replace(/[^A-Za-z0-9_.-]/g,''));
  return r.body;
}
async function subjects(c){
  let cursor=0,result=[];
  for(let page=0;page<100;page++){
    const j=await api(c,'/mweb/v1/dreamina_subject/get',{cursor,limit:20});
    if(!Array.isArray(j.data?.data_list))throw new Error('Subject list format is unsupported');result.push(...j.data.data_list);
    if(!j.data.has_more)return result;
    if(j.data.next_cursor===undefined||j.data.next_cursor===cursor)throw new Error('Invalid subject cursor');cursor=j.data.next_cursor;
  }throw new Error('Subject list pagination limit reached');
}
function atomic(file,value){
  const tmp=file+'.tmp';fs.writeFileSync(tmp,JSON.stringify(value,null,2),'utf8');
  for(let attempt=0;;attempt++){
    try{fs.renameSync(tmp,file);return;}catch(e){
      if(!['EPERM','EACCES','EBUSY'].includes(e.code)||attempt>=20)throw e;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,100);
    }
  }
}
async function uploadImage(c,item,bytes,onStage){
  const credential=(await api(c,'/mweb/v1/get_upload_token',{scene:2})).data;
  if(credential?.upload_domain!=='imagex.bytedanceapi.com'||!credential.secret_access_key||!credential.session_token)throw new Error('Unsupported upload credential response');
  const apply=await imageX('ApplyImageUpload',{FileSize:bytes.length,s:crypto.randomBytes(5).toString('hex')},null,credential);
  // Match the browser SDK's captured inner-upload gateway when available.
  const inner=apply.InnerUploadAddress?.UploadNodes?.[0];
  const addr=inner?{...inner,UploadHosts:[inner.UploadHost]}:apply.UploadAddress,store=addr?.StoreInfos?.[0],host=addr?.UploadHosts?.[0];
  if(!store?.StoreUri||!store.Auth||!addr.SessionKey||!host||!/^tos-[a-z0-9-]+\.(snssdk|bytedancevod)\.com$/.test(host))throw new Error('Unsupported official upload address; stopped');
  if(!/^tos-cn-i-[a-z0-9]+\/[a-zA-Z0-9_-]+$/.test(store.StoreUri))throw new Error('Unsupported storage path');
  onStage('upload-started');
  let response;try{response=await fetch('https://'+host+'/upload/v1/'+store.StoreUri,{method:'POST',headers:{'content-type':'application/octet-stream','authorization':store.Auth,'content-crc32':crc32(bytes)},body:bytes,redirect:'error',signal:AbortSignal.timeout(120000)});}catch{throw new Error('File upload outcome uncertain; stopped without retry');}
  if(!response.ok)throw new Error('File upload rejected: HTTP '+response.status);await response.arrayBuffer();
  const committed=await imageX('CommitImageUpload',{}, {SessionKey:addr.SessionKey},credential);
  const result=committed.Results?.find(r=>r.Uri===store.StoreUri);
  if(!result||result.UriStatus!==2000)throw new Error('Upload commit not confirmed');
  onStage('upload-committed');
  await api(c,'/mweb/v1/imagex/submit_audit_job',{uri_list:[store.StoreUri]});
  const lookup=await api(c,'/mweb/v1/get_image_by_uri',{uris:[store.StoreUri]});
  const image=lookup.uri2image?.[store.StoreUri];
  const dimensions=imageSize(bytes);
  // The official lookup may initially return 0x0 while metadata processing runs.
  // The web uploader submits dimensions decoded from the local main image.
  if(!image?.image_uri||!image.image_url||
     (image.width&&image.width!==dimensions.width)||(image.height&&image.height!==dimensions.height))throw new Error('Uploaded image readback is invalid');
  const url=new URL(image.image_url);if(url.protocol!=='https:'||!url.hostname.endsWith('.byteimg.com'))throw new Error('Unsupported image preview host');
  return {...dimensions,image_uri:image.image_uri,image_url:image.image_url};
}
async function runWaves(items,concurrency,work,verify){
  if(!Number.isInteger(concurrency)||concurrency<1||concurrency>8)throw new Error('Concurrency must be 1..8');
  for(let i=0;i<items.length;i+=concurrency){
    const settled=await Promise.allSettled(items.slice(i,i+concurrency).map(work));
    const done=settled.filter(r=>r.status==='fulfilled').map(r=>r.value);
    if(done.length)await verify(done);
    const failed=settled.filter(r=>r.status==='rejected');
    if(failed.length)throw new Error('Stopped after current wave: '+failed.map(r=>r.reason?.message||'request failed').join(' | '));
  }
}
async function main(){
  const args=process.argv.slice(2);
  if(!['--sample','--all'].includes(args[0])||(args.length!==1&&!(args.length===3&&args[1]==='--concurrency')))throw new Error('Use --sample or --all [--concurrency 1..8] after user approval');
  const concurrency=args.length===3?Number(args[2]):args[0]==='--sample'?1:6;
  if(!Number.isInteger(concurrency)||concurrency<1||concurrency>8)throw new Error('Concurrency must be 1..8');
  const plan=JSON.parse(fs.readFileSync((process.env.OFFICIAL_SUBJECT_PLAN ? path.resolve(process.env.OFFICIAL_SUBJECT_PLAN) : path.join(__dirname,'.data','official-subject-upload-plan.json')),'utf8'));
  if(!plan.categoryMappingsConfirmed||!plan.shortNamesConfirmed)throw new Error('Naming plan is not confirmed');
  const selectedNames=plan.sampleNames||['浪子回头-人设-中山装男人','浪子回头-场景-村口','浪子回头-道具-玉佩-龙形玉佩状态'];
  const items=args[0]==='--sample'?selectedNames.map(n=>{const i=plan.items.find(i=>i.title===n);if(!i)throw new Error('Sample is missing');return i;}):plan.items;
  const progressFile=path.join(__dirname,'.data','official-subject-api-progress.json');
  const progress=fs.existsSync(progressFile)?JSON.parse(fs.readFileSync(progressFile,'utf8')):{destination:'official-subject-library',items:{}};
  const lockFile=path.join(__dirname,'.data','official-subject-upload.lock');
  let lock;
  try{lock=fs.openSync(lockFile,'wx');fs.writeFileSync(lock,String(process.pid));}catch{throw new Error('Another upload may be running; inspect the upload lock before retry');}
  const c=new ChromeAPI();let added=0,skipped=0;
  try{
    await c.connect();let existing=await subjects(c);
    const pending=[];
    // Validate all local files and remote-name collisions before any new upload.
    for(const item of items){
      if(item.title.length>20)throw new Error('Name is over 20 characters');
      const bytes=fs.readFileSync(item.stagedFile);if(!bytes.length||bytes.length>32*1024*1024||sha(bytes)!==item.sha256)throw new Error('Source file changed or over size limit; stopped');imageSize(bytes);
      const duplicate=existing.filter(s=>s.content?.name===item.title);
      if(duplicate.length>1)throw new Error('Duplicate remote names require review: '+item.title);
      if(duplicate.length===1){
        const prior=progress.items[item.title];
        if(prior?.sha256&&prior.sha256!==item.sha256)throw new Error('Local source changed for existing subject: '+item.title);
        if(prior?.subjectId&&prior.subjectId!==duplicate[0].subject_id)throw new Error('Remote subject identity changed: '+item.title);
        if(!prior||prior.status!=='verified')progress.items[item.title]={status:'existing-skipped',subjectId:duplicate[0].subject_id,sha256:item.sha256};
        atomic(progressFile,progress);skipped++;console.log('EXISTING '+item.title);continue;
      }
      // No subject-create request has been sent in these stages. The remote
      // list above confirms the name is absent; restarting image transfer
      // cannot duplicate a subject. Never auto-retry create-stage outcomes.
      const prior=progress.items[item.title];if(prior&&!['prepared','upload-started','upload-committed','create-rejected'].includes(prior.status))throw new Error('Previous partial outcome requires review: '+item.title);
      pending.push(item);
    }
    progress.lastRun={mode:args[0],concurrency,pending:pending.length,skipped,startedAt:new Date().toISOString(),status:'running'};atomic(progressFile,progress);
    console.log(JSON.stringify({pending:pending.length,skipped,concurrency}));
    await runWaves(pending,concurrency,async item=>{
      const bytes=fs.readFileSync(item.stagedFile);if(sha(bytes)!==item.sha256)throw new Error('Source changed after preflight: '+item.title);
      const setStage=status=>{progress.items[item.title]={status,sha256:item.sha256,time:new Date().toISOString()};atomic(progressFile,progress);};
      setStage('prepared');
      const image=await uploadImage(c,item,bytes,setStage);
      setStage('create-started');
      let created;
      try{created=(await api(c,'/mweb/v1/dreamina_subject/create',{content:{name:item.title,description:item.description,main_image:image}})).data;}
      catch(e){setStage('create-outcome-uncertain');throw e;}
      if(!created?.subject_id||created.content?.name!==item.title||created.content?.main_image?.image_uri!==image.image_uri||!created.subject_control?.enabled)throw new Error('Create response failed validation');
      progress.items[item.title]={status:'created-awaiting-readback',subjectId:created.subject_id,sha256:item.sha256};atomic(progressFile,progress);
      return {item,image,subjectId:created.subject_id};
    },async done=>{
      existing=await subjects(c);
      for(const {item,image,subjectId} of done){
        const found=existing.find(s=>s.subject_id===subjectId);
        if(!found||found.content?.name!==item.title||found.content?.main_image?.image_uri!==image.image_uri||found.content?.description!==item.description||!found.subject_control?.enabled)throw new Error('Saved subject readback failed: '+item.title);
        progress.items[item.title].status='verified';atomic(progressFile,progress);added++;console.log('VERIFIED '+item.title);
      }
      console.log(JSON.stringify({verifiedThisRun:added,pending:pending.length-added,skipped}));
    });
    const remote=await subjects(c);
    for(const item of items){
      const matches=remote.filter(s=>s.content?.name===item.title);
      if(matches.length!==1||matches[0].subject_id!==progress.items[item.title]?.subjectId||!matches[0].subject_control?.enabled)throw new Error('Final full-library verification failed: '+item.title);
    }
    progress.lastRun.status='complete';progress.lastRun.completedAt=new Date().toISOString();progress.lastRun.added=added;progress.lastRun.totalCovered=items.length;atomic(progressFile,progress);
    console.log(JSON.stringify({added,skipped,totalCovered:items.length,concurrency,batchStarted:args[0]==='--all',finalVerified:true}));
  }catch(e){
    if(progress.lastRun?.status==='running'){progress.lastRun.status='stopped';progress.lastRun.verifiedThisRun=added;atomic(progressFile,progress);}throw e;
  }finally{c.close();fs.closeSync(lock);fs.unlinkSync(lockFile);}
}
if(require.main===module)main().catch(e=>{console.error(e.message||'Upload stopped');process.exitCode=1;});
module.exports={signImageX,crc32,pngSize,imageSize,runWaves};


