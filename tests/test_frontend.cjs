// Pure state/DOM-unit tests, no browser automation or external services.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.handlers={};this.value='';this.disabled=false;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];}
  addEventListener(event,fn){this.handlers[event]=fn;}
  setAttribute(key,value){this[key]=value;}
  showModal(){this.open=true;}
  close(){this.open=false;}
  pause(){this.paused=true;}
  removeAttribute(key){delete this[key];}
  load(){this.loaded=true;}
  remove(){this.removed=true;}
}
const elements = new Map();
const context = vm.createContext({
  document:{getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},
    createElement:tag=>new Element(tag),querySelectorAll:()=>[]},
  window:{addEventListener(){}},URL:class extends URL {static createObjectURL(){return 'blob:local';}static revokeObjectURL(){}},
  crypto,URLSearchParams,Blob,console,localStorage:{getItem(){return null;},setItem(){}},
  fetch:()=>new Promise(()=>{}),setInterval(){},setTimeout(){},confirm:()=>false,prompt:()=>null,
});
vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
function evaluate(source){return vm.runInContext(source,context);}
evaluate(`addFiles([{name:'人物.jpg',size:1024,lastModified:1},{name:'人物.png',size:1024,lastModified:2}],false)`);
assert.equal(evaluate('groups().size'),2,'ordinary files must not accidentally merge');
evaluate(`state.draft.forEach(r=>{r.group='同一主体';r.main=true;});renderDraft()`);
assert.equal(evaluate('groups().size'),1);
assert.equal(evaluate('state.draft.filter(r=>r.main).length'),1,'merged group has exactly one main');
assert.equal(evaluate('state.draft.filter(r=>!r.main).length'),1,'no auxiliary image gets dropped');
evaluate(`clearDraft();addFiles([{name:'主图.png',size:1024,lastModified:1,webkitRelativePath:'素材/商品A/主图.png'},
 {name:'细节.png',size:1024,lastModified:2,webkitRelativePath:'素材/商品A/细节.png'},
 {name:'主图.png',size:1024,lastModified:3,webkitRelativePath:'素材/商品B/主图.png'}],true)`);
assert.equal(evaluate('groups().size'),2);
assert.equal(evaluate(`groups().get('素材/商品A').length`),2);
assert.equal(evaluate(`state.draft.filter(r=>r.main).length`),2);
evaluate(`addFiles([{name:'bad.exe',size:100,lastModified:1},{name:'empty.png',size:0,lastModified:1},
 {name:'large.png',size:33*1024*1024,lastModified:1}],false)`);
assert.equal(evaluate('state.draft.length'),3,'invalid files skipped');
evaluate(`addFiles([{name:'主图.png',size:1024,lastModified:1,webkitRelativePath:'素材/商品A/主图.png'}],true)`);
assert.equal(evaluate('state.draft.length'),3,'duplicate file selection skipped');
evaluate(`state.batchId='previous';invalidateDraft()`);
assert.equal(evaluate('state.batchId'),null);
assert.equal(evaluate(`parseAssetProjectRules('浪子回头|浪子,浪回\\n乡土').length`),2);
assert.equal(evaluate(`parseAssetProjectRules('浪子回头|浪子，浪回')[0].aliases.length`),2);
assert.throws(()=>evaluate(`parseAssetProjectRules('A|B|C')`));
assert.equal(evaluate(`validatePlaybackSource('https://v26-artist.vlabvod.com/video.mp4?temporary=1')`),'https://v26-artist.vlabvod.com/video.mp4?temporary=1');
for(const value of ['http://v26-artist.vlabvod.com/video.mp4','https://evil.example/video.mp4','https://v26-artist.vlabvod.com.evil.example/a','https://user:pass@v26-artist.vlabvod.com/a','https://v26-artist.vlabvod.com:8443/a','javascript:alert(1)','https://jimeng.jianying.com/ai-tool/asset'])
  assert.throws(()=>evaluate(`validatePlaybackSource(${JSON.stringify(value)})`));
evaluate(`openAssetPreview({recordId:'local-test',projectName:'其他',duration:'25s'})`);
assert.equal(elements.get('preview').open,true);
evaluate(`playAssetSource('https://v26-artist.vlabvod.com/test.mp4',document.createElement('p'))`);
assert.equal(evaluate('activePreview.controls'),true);
evaluate(`activePreview.duration=25;activePreview.handlers.loadedmetadata();activePreview.handlers.error()`);
evaluate(`stopPreview()`);
assert.equal(evaluate('activePreview'),null);
assert.equal(elements.get('previewBody').children.length,0);
assert.equal(evaluate('assetPlayback.size'),0,'playback renderer must not persist a URL by itself');
console.log('Frontend state and preview tests passed.');
