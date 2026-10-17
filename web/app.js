'use strict';
const $ = id => document.getElementById(id);
const state = {csrf:'', canvases:[], cursor:null, draft:[], descriptions:{}, jobs:[], batchId:null,
  busy:false, videoOffset:0, subjectOffset:0, videoHasMore:false, subjectHasMore:false,
  videoItems:[], subjectItems:[], currentTab:'videos', generations:{video:0,subject:0},
  assetOffset:0,assetGeneration:0,assetItems:[],assetHasMore:false,assetProjectsLoaded:false};
const statuses = {queued:'排队中',running:'处理中',success:'成功',paused:'暂停 / 待核对',failed:'失败',
  empty:'尚未生成',partial_success:'部分成功',canceled:'取消',unknown:'未知'};
// Playback sources never enter API calls, localStorage, exports or catalogue data.
const assetPlayback = new Map();
let activePreview = null;
function validatePlaybackSource(value){
  let u;try{u=new URL(value);}catch{throw new Error('请输入有效的官方临时播放地址');}
  if(u.protocol!=='https:'||!['v3-artist.vlabvod.com','v26-artist.vlabvod.com'].includes(u.hostname)||u.username||u.password||u.port)
    throw new Error('仅接受已核对的即梦视频播放域名，不接受网页链接或其他来源');
  return u.href;
}
function stopPreview(){
  if(activePreview){activePreview.pause();activePreview.removeAttribute('src');activePreview.load();activePreview=null;}
  $('previewBody').replaceChildren();
}
function playAssetSource(source,status){
  if(activePreview){activePreview.pause();activePreview.removeAttribute('src');activePreview.load();activePreview.remove();}
  const video=el('video');video.controls=true;video.preload='metadata';video.playsInline=true;
  video.setAttribute('aria-label','视频资产播放器');activePreview=video;
  status.textContent='正在加载视频…';
  video.addEventListener('loadedmetadata',()=>{if(activePreview===video)status.textContent=`视频已就绪 · ${video.duration.toFixed(1)} 秒，点击播放器播放`;});
  video.addEventListener('playing',()=>{if(activePreview===video)status.textContent='正在播放';});
  video.addEventListener('error',()=>{if(activePreview===video)status.textContent='播放失败：地址可能已过期、访问受限或编码不支持。请重新接入官方详情播放源，或选择已下载的视频；不会自动重试或生成。';});
  video.src=source;$('previewBody').append(video);
}
function openAssetPreview(item){
  stopPreview();const body=$('previewBody');body.append(el('h3',item.projectName+' · '+(item.duration||'视频')));
  const status=el('p','此记录尚未接入播放源。可让 Agent 从对应官方详情接入，或选择本地视频。');status.setAttribute('role','status');
  body.append(status);
  const link=safeLink('https://jimeng.jianying.com/ai-tool/asset','打开官方视频资产页');if(link)body.append(link);
  const localLabel=el('label','选择已下载的视频（不上传）'),file=el('input');file.type='file';file.accept='video/*';file.setAttribute('aria-label','选择本地视频预览');
  localLabel.append(file);body.append(localLabel);
  file.addEventListener('change',()=>{const f=file.files?.[0];if(!f)return;
    if(!f.size||(!f.type.startsWith('video/')&&!/\.(mp4|webm|mov|m4v|ogv)$/i.test(f.name))){status.textContent='请选择非空的视频文件';return;}
    const old=assetPlayback.get(item.recordId);if(old?.local)URL.revokeObjectURL(old.source);
    const source=URL.createObjectURL(f);assetPlayback.set(item.recordId,{source,local:true});playAssetSource(source,status);file.value='';});
  const settings=el('details'),summary=el('summary','临时官方播放源（仅本页内存）');settings.append(summary);
  const input=el('input');input.type='password';input.autocomplete='off';input.setAttribute('aria-label','临时官方视频播放地址');
  settings.append(el('p','此处不是资产页网址。播放源须来自对应官方详情的视频元素，不能把其他视频接错；有效期由官方决定。'),input,action('接入并预览',async()=>{
    try{const source=validatePlaybackSource(input.value.trim()),old=assetPlayback.get(item.recordId);if(old?.local)URL.revokeObjectURL(old.source);
      assetPlayback.set(item.recordId,{source,local:false});input.value='';playAssetSource(source,status);
    }catch(e){input.value='';status.textContent=e.message;}
  }));body.append(settings);
  const saved=assetPlayback.get(item.recordId);if(saved)playAssetSource(saved.source,status);
  $('preview').showModal();
}
function el(tag, content, cls){const e=document.createElement(tag);if(content!==undefined)e.textContent=content;if(cls)e.className=cls;return e;}
function notice(message){$('notice').textContent=message||'';}
function detailError(e){const d=e.info||{};return [e.message,d.requiredAction?`下一步：${d.requiredAction}`:'',d.requestId?`请求 ID：${d.requestId}`:''].filter(Boolean).join('\n');}
async function api(path, data, raw=false){
  const opts=data===undefined?{}:{method:'POST',headers:{'Content-Type':raw?'application/octet-stream':'application/json','X-CSRF-Token':state.csrf},body:raw?data:JSON.stringify(data)};
  const r=await fetch(path,opts);let j;try{j=await r.json();}catch{throw new Error('本地服务未返回有效数据，请检查是否仍在运行');}
  if(!r.ok||j.error){const e=new Error(j.error?.message||'请求失败');e.info=j.error;throw e;}return j;
}
function action(label,callback){const b=el('button',label);b.addEventListener('click',()=>run(b,callback));return b;}
async function run(button,fn){if(button.disabled)return;button.disabled=true;try{await fn();}catch(e){notice(detailError(e));}finally{button.disabled=false;}}
function bind(id,fn){$(id).addEventListener('click',()=>run($(id),fn));}
function project(){const id=$('canvas').value;if(!id)throw new Error('请先选择目标画布');return id;}
function canvasLink(p){return state.canvases.find(c=>c.projectId===p)?.webUrl;}
function safeLink(url,label){try{const u=new URL(url);if(u.protocol!=='https:'||u.hostname!=='jimeng.jianying.com')return null;const a=el('a',label);a.href=u.href;a.target='_blank';a.rel='noreferrer noopener';return a;}catch{return null;}}
function showTab(name){state.currentTab=name;document.querySelectorAll('.tab').forEach(e=>e.hidden=e.id!==name);document.querySelectorAll('nav button').forEach(e=>e.setAttribute('aria-pressed',String(e.dataset.tab===name)));if(name==='jobs')refreshJobs().catch(e=>notice(detailError(e)));if(name==='assets')loadAssets().catch(e=>notice(detailError(e)));}
document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>showTab(b.dataset.tab)));

async function refreshAccount(){const d=await api('/api/status');$('account').textContent=`CLI ${d.version.version} · ${d.auth.loggedIn?'已登录':'未登录'}${d.account?.vipLevel?' · '+d.account.vipLevel:''}`;if(d.auth.expiresAt)$('account').title='当前凭据有效期：'+d.auth.expiresAt;if(d.auth.loggedIn)$('loginLink').replaceChildren();return d;}
async function loadCanvases(more=false){
  const old=$('canvas').value;const d=await api('/api/canvases'+(more&&state.cursor?'?cursor='+encodeURIComponent(state.cursor):''));
  state.canvases=more?[...state.canvases,...d.items]:d.items||[];
  state.canvases=[...new Map(state.canvases.map(c=>[c.projectId,c])).values()];state.cursor=d.nextCursor||null;
  $('moreCanvas').hidden=!d.hasMore||!state.cursor;
  $('canvas').replaceChildren(el('option','请选择画布'));
  $('canvas').firstChild.value='';
  for(const c of state.canvases){const o=el('option',(c.name||'未命名画布')+' · '+c.projectId.slice(0,8));o.value=c.projectId;$('canvas').append(o);}
  const saved=old||localStorage.getItem('dreamina.project');if(state.canvases.some(c=>c.projectId===saved))$('canvas').value=saved;
  else if(state.canvases.length===1)$('canvas').value=state.canvases[0].projectId;
  await canvasChanged();
}
async function canvasChanged(){
  state.videoOffset=state.subjectOffset=0;state.batchId=null;
  const id=$('canvas').value;localStorage.setItem('dreamina.project',id);
  const link=safeLink(canvasLink(id),'打开即梦画布');$('canvasLink').hidden=!link;if(link)$('canvasLink').href=link.href;
  $('videoRows').replaceChildren();$('subjectRows').replaceChildren();
  if(id)await Promise.allSettled([loadNodes('video'),loadNodes('subject')]).then(results=>{for(const r of results)if(r.status==='rejected')notice(detailError(r.reason));});
}
$('canvas').addEventListener('change',()=>canvasChanged().catch(e=>notice(detailError(e))));
async function loadNodes(kind){
  const p=project(), generation=++state.generations[kind];
  const offset=state[kind+'Offset'];const type=kind==='video'?'video':'element';
  const q=new URLSearchParams({project:p,type,offset:String(offset),name:$(kind+'Search').value});
  if(kind==='video')q.set('status',$('videoStatus').value);
  const d=await api('/api/nodes?'+q);
  if(generation!==state.generations[kind]||p!==$('canvas').value)return;
  state[kind+'HasMore']=Boolean(d.hasMore);state[kind+'Items']=d.items||[];
  const rows=$(kind+'Rows');rows.replaceChildren();
  for(const item of d.items||[]){
    const tr=el('tr'),name=el('td',item.title||'未命名');name.append(el('small',item.nodeId));tr.append(name,el('td',statuses[item.status]||item.status||'—'));
    if(kind==='video')tr.append(el('td',item.localNote||'—'));
    const td=el('td');td.append(action('详情',()=>openDetail(p,item)));const a=safeLink(canvasLink(p),'打开画布');if(a){td.append(' ',a);}tr.append(td);rows.append(tr);
  }
  if(!rows.children.length){const td=el('td','没有匹配节点');td.colSpan=kind==='video'?4:3;const tr=el('tr');tr.append(td);rows.append(tr);}
  $(kind+'Page').textContent=`第 ${Math.floor(offset/50)+1} 页 · 当前 ${d.items?.length||0} 项 · 查询总数 ${d.total??'未知'}`;
  $(kind+'Prev').disabled=offset===0;$(kind+'Next').disabled=!d.hasMore||offset+50>1000;
}
for(const kind of ['video','subject']){
  bind(kind==='video'?'findVideos':'findSubjects',async()=>{state[kind+'Offset']=0;await loadNodes(kind);});
  for(const [side,delta] of [['Prev',-50],['Next',50]])$(kind+side).addEventListener('click',async()=>{state[kind+'Offset']=Math.max(0,state[kind+'Offset']+delta);try{await loadNodes(kind);}catch(e){notice(detailError(e));}});
}
async function openDetail(p,item){
  $('detailTitle').textContent='节点详情';
  const d=await api('/api/node?'+new URLSearchParams({project:p,node:item.nodeId}));if(!d.node)throw new Error('节点不存在或不可访问，请刷新列表');
  const n=d.node,body=$('detailBody');body.replaceChildren(el('h3',n.title||item.nodeId));
  const generation=n.generation||{};if(generation.prompt){body.append(el('h4','提示词'),el('pre',generation.prompt));}
  const info={nodeId:n.nodeId,type:n.type,status:n.status,generation:n.generation,subjectBindings:n.subjectBindings,upstreamNodeIds:n.upstreamNodeIds,resources:n.resources};
  body.append(el('pre',JSON.stringify(info,null,2)));
  for(const r of n.resources||[]){const line=el('div',`${r.type} · ${statuses[r.status]||r.status} · ${r.resourceId} `);if(r.status==='success')line.append(action('请求 CLI 下载',async()=>{await api('/api/download',{project:p,resource:r.resourceId,type:r.type});notice('下载已进入队列；视频是否支持以 CLI 实际返回为准。可在任务队列查看。');await refreshJobs();}));body.append(line);}
  const label=el('label','本地备注（不修改即梦画布）'),area=el('textarea');area.value=item.localNote||'';area.maxLength=3000;label.append(area);body.append(label,action('保存备注',async()=>{await api('/api/note',{project:p,node:item.nodeId,note:area.value});item.localNote=area.value;notice('本地备注已保存');if($('canvas').value===p)await loadNodes(item.type==='element'?'subject':'video');}));
  $('detail').showModal();
}
bind('closeDetail',async()=>$('detail').close());bind('closePreview',async()=>{$('preview').close();stopPreview();});
$('preview').addEventListener('close',stopPreview);

function parseAssetProjectRules(value){
  return value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map(line=>{
    const parts=line.split('|');if(parts.length>2)throw new Error('规则格式：剧名|简称1,简称2');
    return {name:parts[0].trim(),aliases:(parts[1]||'').split(/[,，]/).map(s=>s.trim()).filter(Boolean)};
  });
}
async function loadAssets(){
  const generation=++state.assetGeneration,selected=$('assetProject').value;
  const d=await api('/api/assets?'+new URLSearchParams({project:selected,search:$('assetSearch').value,offset:String(state.assetOffset)}));
  if(generation!==state.assetGeneration)return;
  state.assetItems=d.items||[];state.assetHasMore=Boolean(d.hasMore);
  $('assetProject').replaceChildren();const all=el('option','全部项目');all.value='';$('assetProject').append(all);
  for(const group of d.groups||[]){const o=el('option',`${group.name} (${group.count})`);o.value=group.name;$('assetProject').append(o);}
  if(selected&&!d.groups.some(g=>g.name===selected)){const o=el('option',selected+' (0)');o.value=selected;$('assetProject').append(o);}
  $('assetProject').value=selected;
  if(!state.assetProjectsLoaded){$('assetProjectRules').value=(d.projects||[]).map(p=>p.name+(p.aliases.length?'|'+p.aliases.join(','):'')).join('\n');state.assetProjectsLoaded=true;}
  $('assetSummary').textContent=`本地已记录 ${d.indexedTotal} 条官方视频详情，当前匹配 ${d.total} 条；不是官方全量同步。`;
  const rows=$('assetRows');rows.replaceChildren();
  for(const item of state.assetItems){
    const tr=el('tr'),name=el('td',item.projectName);name.append(el('small',item.classificationReason));
    const prompt=el('td',(item.prompt||'无提示词').slice(0,140));prompt.className='asset-prompt';
    tr.append(name,prompt,el('td',[item.date||'日期未提供',item.duration||'时长未提供'].join('\n')),el('td',[item.model,item.resolution,item.ratio].filter(Boolean).join('\n')||'未提供'));
    const td=el('td');td.append(action('预览',async()=>openAssetPreview(item)),action('查看完整提示词',async()=>{
      $('detailTitle').textContent='视频资产详情';
      const body=$('detailBody');body.replaceChildren(el('h3',item.projectName+' · 视频资产'),el('p',item.classificationReason),el('pre',item.prompt||'没有提示词'),el('p','来源：官方视频资产页已读取详情；本地清单不是实时状态。'));
      const link=safeLink('https://jimeng.jianying.com/ai-tool/asset','去官方资产页预览/下载');if(link)body.append(link);
      $('detail').showModal();
    }));tr.append(td);rows.append(tr);
  }
  if(!rows.children.length){const tr=el('tr'),td=el('td',d.indexedTotal?'没有匹配的视频资产':'尚未导入官方视频详情清单；不会用画布视频充当资产数据');td.colSpan=5;tr.append(td);rows.append(tr);}
  $('assetPage').textContent=`第 ${Math.floor(state.assetOffset/50)+1} 页 · ${state.assetItems.length} 条`;
  $('assetPrev').disabled=state.assetOffset===0;$('assetNext').disabled=!state.assetHasMore;
}
bind('findAssets',async()=>{state.assetOffset=0;await loadAssets();});
bind('refreshAssets',async()=>{state.assetOffset=0;await loadAssets();});
$('assetProject').addEventListener('change',async()=>{state.assetOffset=0;try{await loadAssets();}catch(e){notice(detailError(e));}});
for(const [side,delta] of [['Prev',-50],['Next',50]])bind('asset'+side,async()=>{state.assetOffset=Math.max(0,state.assetOffset+delta);await loadAssets();});
bind('saveAssetProjects',async()=>{
  const projects=parseAssetProjectRules($('assetProjectRules').value);
  await api('/api/assets/projects',{projects});state.assetOffset=0;await loadAssets();notice('剧名规则已保存，视频按提示词开头重新分类；官方资产未修改。');
});
bind('importAssets',async()=>{
  const file=$('assetManifest').files?.[0];if(!file)throw new Error('请选择视频详情 JSON 清单');
  if(file.size>2*1024*1024)throw new Error('每批清单不能超过2MiB，请分批导入');
  let data;try{data=JSON.parse(await file.text());}catch{throw new Error('清单不是有效JSON');}
  if(!confirm('将此官方视频详情清单保存到本地并按提示词剧名分类？不修改、下载或生成官方资产。'))return;
  const result=await api('/api/assets/import',data);state.assetOffset=0;await loadAssets();notice(`新增 ${result.added} 条，复用/更新 ${result.updated} 条本地记录。`);
});
bind('exportAssets',async()=>{
  const data=await api('/api/assets/export');if(!data.items.length)throw new Error('本地清单为空，尚不能导出');
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='jimeng-video-assets.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

function invalidateDraft(){state.batchId=null;}
function addFiles(files,folder){
  if(state.busy)return;
  let skipped=0;
  for(const file of files){
    if(!/\.(png|jpe?g|webp|gif)$/i.test(file.name)){skipped++;continue;}
    if(file.size===0||file.size>32*1024*1024){skipped++;continue;}
    const relative=file.webkitRelativePath||file.name;
    if(state.draft.some(r=>r.relative===relative&&r.file.size===file.size&&r.file.lastModified===file.lastModified))continue;
    const parts=relative.split('/');parts.pop();
    const base=folder&&parts.length?parts.join('/'):file.name.replace(/\.[^.]+$/,'');
    let group=base;
    if(!folder){const used=new Set(state.draft.map(r=>r.group));let i=2;while(used.has(group))group=base+' ('+(i++)+')';}
    state.draft.push({key:crypto.randomUUID(),file,relative,group,checked:false,main:false,local:null,url:URL.createObjectURL(file),error:''});
  }
  invalidateDraft();renderDraft();notice(skipped?`跳过 ${skipped} 个非图片、空文件或超过 32MB 的文件。`:'图片已加入草稿，尚未上传到即梦。');
}
$('images').addEventListener('change',e=>{addFiles(e.target.files,false);e.target.value='';});
$('folder').addEventListener('change',e=>{addFiles(e.target.files,true);e.target.value='';});
function groups(){const result=new Map();for(const r of state.draft){const key=r.group.trim();if(!result.has(key))result.set(key,[]);result.get(key).push(r);}return result;}
function renderDescriptions(){const area=$('groupDescriptions');area.replaceChildren();for(const name of groups().keys()){const label=el('label',`主体「${name||'未命名'}」的描述（可选）`),input=el('textarea');input.maxLength=3000;input.value=state.descriptions[name]||'';input.disabled=state.busy;input.addEventListener('input',()=>{state.descriptions[name]=input.value;invalidateDraft();});label.append(input);area.append(label);}}
function renderDraft(){
  const rows=$('draftRows');rows.replaceChildren();
  const gs=groups();for(const entries of gs.values()){const chosen=entries.find(r=>r.main)||entries[0];entries.forEach(r=>r.main=r===chosen);}
  for(const row of state.draft){
    const tr=el('tr'),check=el('input');check.type='checkbox';check.checked=row.checked;check.disabled=state.busy;check.setAttribute('aria-label','选择 '+row.relative);check.addEventListener('change',()=>row.checked=check.checked);let td=el('td');td.append(check);tr.append(td);
    const img=el('img');img.src=row.url;img.alt=row.file.name;td=el('td');td.append(img);tr.append(td);
    const name=el('td',row.relative);name.append(el('small',(row.file.size/1024/1024).toFixed(2)+' MB'));tr.append(name);
    const input=el('input');input.value=row.group;input.maxLength=300;input.disabled=state.busy;input.setAttribute('aria-label','主体分组名称');input.addEventListener('change',()=>{row.group=input.value.trim();row.main=false;invalidateDraft();renderDraft();});td=el('td');td.append(input);tr.append(td);
    const main=el('input');main.type='radio';main.name='main-'+row.group;main.checked=row.main;main.disabled=state.busy;main.setAttribute('aria-label','将 '+row.file.name+' 设为主图');main.addEventListener('change',()=>{for(const r of state.draft)if(r.group===row.group)r.main=r===row;invalidateDraft();renderDraft();});td=el('td');td.append(main);tr.append(td);
    tr.append(el('td',row.error|| (row.local?'已暂存本机':'未暂存'),row.error?'error':''));td=el('td');const remove=action('移除',async()=>{URL.revokeObjectURL(row.url);state.draft=state.draft.filter(r=>r!==row);invalidateDraft();renderDraft();});remove.disabled=state.busy;td.append(remove);tr.append(td);rows.append(tr);
  }
  $('draftSummary').textContent=`${state.draft.length} 张图片，${gs.size} 个主体组。第一版只支持图片主素材与辅助图。`;
  for(const id of ['images','folder','merge','split','clearDraft','selectAll','canvas','refreshCanvas','moreCanvas'])$(id).disabled=state.busy;
  renderDescriptions();
}
$('selectAll').addEventListener('change',e=>{state.draft.forEach(r=>r.checked=e.target.checked);renderDraft();});
bind('merge',async()=>{const chosen=state.draft.filter(r=>r.checked);if(!chosen.length)throw new Error('请先勾选图片');const name=prompt('合并后的主体名称',chosen[0].group);if(name===null)return;if(!name.trim())throw new Error('主体名称不能为空');chosen.forEach((r,i)=>{r.group=name.trim();r.main=i===0;});invalidateDraft();renderDraft();});
bind('split',async()=>{const used=new Set(state.draft.filter(r=>!r.checked).map(r=>r.group));state.draft.filter(r=>r.checked).forEach(r=>{const base=r.file.name.replace(/\.[^.]+$/,'');let name=base,i=2;while(used.has(name))name=base+' ('+(i++)+')';used.add(name);r.group=name;r.main=true;});invalidateDraft();renderDraft();});
function clearDraft(){state.draft.forEach(r=>URL.revokeObjectURL(r.url));state.draft=[];state.descriptions={};state.batchId=null;renderDraft();}
bind('clearDraft',async()=>{if(state.draft.length&&!confirm('清空当前未提交草稿？已进入队列的任务不会受影响。'))return;clearDraft();});
bind('submitSubjects',async()=>{
  const p=project(), gs=groups();if(!gs.size||gs.size>200)throw new Error('每批需要 1–200 个主体');
  for(const [name,rows] of gs){if(!name||name.length>300||rows.length>30)throw new Error('请检查主体名称及每组数量（最多 30 张）');}
  const c=state.canvases.find(c=>c.projectId===p);
  if(!confirm(`将 ${state.draft.length} 张图片上传到即梦，创建 ${gs.size} 个主体。\n目标：${c?.name||'未命名画布'}\n画布 ID：${p}\n只保存，不生成、不批准积分。是否继续？`))return;
  state.busy=true;renderDraft();state.batchId=state.batchId||crypto.randomUUID();
  try{
    for(let i=0;i<state.draft.length;i++){
      const r=state.draft[i];$('uploadProgress').textContent=`本地暂存 ${i+1}/${state.draft.length}`;
      if(!r.local){try{r.local=await api('/api/upload?'+new URLSearchParams({name:r.relative}),r.file,true);r.error='';}catch(e){r.error=e.message;throw e;}}
    }
    const payload=[...gs].map(([title,rows])=>({title,description:state.descriptions[title]||'',files:[...rows.filter(r=>r.main).slice(0,1),...rows.filter(r=>!r.main)].map(r=>r.local.id)}));
    // Frozen request identity survives a failed HTTP response while the draft stays open.
    const result=await api('/api/subjects',{project:p,batchId:state.batchId,groups:payload});
    clearDraft();notice(`${new Set(result.jobIds).size} 个任务已加入队列或复用原任务。相同画布、名称、描述和素材内容不会重复建任务。`);showTab('jobs');await refreshJobs();
  }finally{state.busy=false;$('uploadProgress').textContent='';renderDraft();}
});

function progress(job){if(job.kind==='download')return job.status==='success'?'已下载并校验 SHA256':'下载任务';const p=job.payload;return `素材 ${p.assets.filter(a=>a.saved).length}/${p.assets.length}，主体 ${p.done?'已确认':'待确认'}`;}
async function refreshJobs(){
  const d=await api('/api/jobs');state.jobs=d.items||[];
  $('queueCount').textContent=state.jobs.filter(j=>['queued','running','paused','failed'].includes(j.status)).length;
  const rows=$('jobRows');rows.replaceChildren();
  for(const j of state.jobs){
    const tr=el('tr'),name=el('td',j.title);name.append(el('small',j.project),el('small',new Date(j.created*1000).toLocaleString()));tr.append(name,el('td',(statuses[j.status]||j.status)+'\n'+progress(j)));
    const error=j.error||{};tr.append(el('td',[error.message,error.requiredAction?'下一步：'+error.requiredAction:'',error.requestId?'请求 ID：'+error.requestId:''].filter(Boolean).join('\n'),j.error?'error':''));
    const td=el('td'),buttons=el('div',undefined,'toolbar');
    if(j.status==='queued')buttons.append(action('暂停等待',async()=>{await api('/api/pause',{jobId:j.id});await refreshJobs();}));
    if(['paused','failed'].includes(j.status))buttons.append(action('核对并恢复',async()=>{await api('/api/resume',{jobId:j.id});await refreshJobs();}));
    const link=safeLink(canvasLink(j.project),'打开原画布');if(link)buttons.append(link);
    if(j.kind==='download'&&j.status==='success'){
      buttons.append(action('预览',async()=>{const area=$('previewBody');area.replaceChildren();const mime=j.payload.mime;let tag=mime.startsWith('video/')?'video':mime.startsWith('image/')?'img':mime.startsWith('audio/')?'audio':null;if(!tag)throw new Error('该文件不支持浏览器预览，请下载');const media=el(tag);media.src='/media/'+j.id;if(tag!=='img'){media.controls=true;media.preload='metadata';}media.addEventListener('error',()=>notice('浏览器无法解码或缓存文件缺失；请下载检查。'));area.append(media);$('preview').showModal();}));
      const a=el('a','保存文件');a.href='/media/'+j.id+'?download=1';a.download='';buttons.append(a);
    }
    td.append(buttons,el('small','任务 ID：'+j.id));if(j.payload.nodeId)td.append(el('small','主体节点：'+j.payload.nodeId));tr.append(td);rows.append(tr);
  }
  if(!rows.children.length){const tr=el('tr'),td=el('td','没有任务');td.colSpan=4;tr.append(td);rows.append(tr);}
}
bind('exportJobs',async()=>{await refreshJobs();const safe=state.jobs.map(j=>({id:j.id,kind:j.kind,projectId:j.project,title:j.title,status:j.status,error:j.error,
  nodeId:j.payload.nodeId,updateId:j.payload.updateId,resourceId:j.payload.resourceId,
  assets:j.payload.assets?.map(a=>({resourceId:a.resourceId,nodeId:a.nodeId,updateId:a.updateId,submitId:a.submitId,uploaded:a.uploaded,saved:a.saved}))}));
  const url=URL.createObjectURL(new Blob([JSON.stringify(safe,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='dreamina-task-records.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
bind('pauseQueued',async()=>{const d=await api('/api/pause',{});notice(`已暂停 ${d.paused} 个尚未开始的任务。正在执行的操作不取消。`);await refreshJobs();});
bind('refreshJobs',refreshJobs);bind('refreshAccount',refreshAccount);bind('refreshCanvas',()=>loadCanvases());bind('moreCanvas',()=>loadCanvases(true));
bind('login',async()=>{const d=await api('/api/login');$('loginLink').replaceChildren();if(d.url){const a=safeLink(d.url,'点击完成即梦授权');if(a)$('loginLink').append(a);notice('请点击官方链接授权；后台正在等待。完成后点击“检查账号”及“刷新画布”。');}else await refreshAccount();});
async function boot(){
  const s=await api('/api/session');state.csrf=s.csrf;
  $('storage').textContent=`仅本机访问。数据目录：${s.dataDirectory}。本地详情清单不保存登录令牌或播放签名链接。`;
  if(s.mode==='video-assets-only'){
    state.assetsOnly=true;document.querySelector('h1').textContent='即梦视频资产管理';
    document.querySelector('body > .toolbar').hidden=true;
    for(const id of ['account','refreshAccount','login','loginLink'])$(id).hidden=true;
    document.querySelectorAll('nav button').forEach(b=>b.hidden=b.dataset.tab!=='assets');
    showTab('assets');return;
  }
  // An already-running older backend serves new static files before restart.
  // Hide the new entry there, instead of allowing an unimplemented API call.
  if(!s.videoAssets)document.querySelectorAll('nav button').forEach(b=>{if(b.dataset.tab==='assets')b.hidden=true;});
  await refreshJobs();try{await refreshAccount();await loadCanvases();}catch(e){notice(detailError(e));}
}
boot().catch(e=>notice(detailError(e)));
let polling=false;setInterval(async()=>{if(state.assetsOnly||polling||document.hidden)return;polling=true;try{await refreshJobs();}catch(e){notice('队列连接失败，请检查本地服务；已记录的任务不会因页面断线而丢失。');}finally{polling=false;}},3000);
window.addEventListener('beforeunload',e=>{if(state.busy||state.draft.length){e.preventDefault();e.returnValue='';}});
