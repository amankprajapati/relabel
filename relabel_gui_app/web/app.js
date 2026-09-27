
const DEFAULT_CLASSES=__CLASSES__;  // from --classes; merged with each project's own class list
let CLASSES=[...DEFAULT_CLASSES];
let classesDirty=false;             // class list edited in the Classes dialog, not yet saved
let clip=document.getElementById('clipsel').value;
let frames=[], cls={}, orig={}, idx=0, selected=null, repIdx={}, edited=new Set();
let addMode=false, draw=null, newN=0, newU=0, drag=null, numMode=false;
let undoStack=[], redoStack=[];
let outName='', srcName='';         // non-destructive: saves go to outName; srcName is never written
let autosaveTimer=null, saving=false, saveAgain=false;   // debounced autosave state
let classFilter='';  // '' = show all classes in the list; else only this class (frame boxes unaffected)
let COMPARE=false, changedIdx=[];   // compare mode: A(before) vs B(after); list of changed frame indices
let _tids=null, idselStale=false;   // perf: cache the sorted object-id list; rebuild merge dropdown lazily
let hidden=new Set();               // frame files whose boxes are hidden (view only; never saved/shifted)
let zoom=1;                         // image zoom factor (boxes recompute from clientWidth -> stay aligned)
let overlapOn=false, overlapIdx=[]; // "high-IoU overlap" filter: frames where two boxes overlap a lot
// (re)build the "Add box" class dropdown from the current CLASSES list (which comes from the JSON)
function buildAddcls(keepCurrent){ const sel=document.getElementById('addcls');
  const keep=keepCurrent?sel.value:'';
  sel.innerHTML=CLASSES.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  if(CLASSES.includes(keep)) sel.value=keep; }
buildAddcls();
const img=()=>document.getElementById('img');

function switchClip(){
  if(dirtyCount()>0) doSave(false);     // autosave: flush this clip's edits before switching (no data loss)
  clip=document.getElementById('clipsel').value; load();
}
async function load(keepIdx,keepSel){
  const d=await (await fetch('/clipdata?clip='+encodeURIComponent(clip))).json();
  frames=d.frames; cls={}; orig={}; selected=keepSel||null; repIdx={}; edited=new Set(); undoStack=[]; redoStack=[]; invalidateTids(); hidden=new Set();
  if(autosaveTimer){ clearTimeout(autosaveTimer); autosaveTimer=null; }
  // class list = the project's declared + used classes, plus any given with --classes
  CLASSES=[...new Set([...(d.class_options||[]), ...DEFAULT_CLASSES])];
  classesDirty=false;
  buildAddcls();
  outName=d.out_name||''; srcName=d.src_name||'';
  { const el=document.getElementById('savetgt');
    if(el) el.innerHTML = outName ? ('Saving to <b>'+esc(outName)+'</b> · original untouched'
        + (d.resumed?' · resumed earlier edits':'')) : ''; }
  zoom=1; { const l=document.getElementById('zoomlbl'); if(l) l.textContent='100%'; }
  overlapOn=false; overlapIdx=[];
  { const b=document.getElementById('ovlbtn'); if(b) b.classList.remove('on');
    const n=document.getElementById('ovlnav'); if(n) n.style.display='none'; }
  for(const t in d.tracks){ cls[t]=d.tracks[t]; orig[t]=d.tracks[t]; }
  // next id for a NEW box = one past the max EXISTING number, so its displayed id (#N) never
  // duplicates an existing object's (previously new boxes always started at #0 -> collided).
  newN=0; presentTids().forEach(t=>{const n=idNum(t); if(isFinite(n))newN=Math.max(newN,n+1);});
  // next internal id for a NEW untracked box = past the max existing "@uN"
  newU=0; frames.forEach(f=>f.regions.forEach(r=>{ if(isUntracked(r.tid)){const n=parseInt(String(r.tid).replace(/\D+/g,''),10); if(isFinite(n))newU=Math.max(newU,n+1);} }));
  computeRepIdx();
  document.getElementById('stat').textContent=frames.length+' frames';
  document.getElementById('slider').max=frames.length-1;
  if(addMode) toggleAdd();
  COMPARE=!!d.compare;
  document.getElementById('stageA').style.display=COMPARE?'flex':'none';
  document.getElementById('capB').style.display=COMPARE?'block':'none';
  document.getElementById('diffnav').style.display=COMPARE?'inline-flex':'none';
  document.getElementById('diffbar').style.display=COMPARE?'block':'none';
  renderList(); go(Math.min(keepIdx||0,frames.length-1)); if(selected) showSel(); refresh(); updBtns();
  if(COMPARE) computeDiff();
}
/* ---- undo / redo — snapshot ONLY the frames an action touches (not the whole dataset).
   Deep-cloning all frames per action made add/undo/redo laggy on large merged projects. ---- */
// for each object, the frame where its box is largest: where clicking it in the list jumps to
function computeRepIdx(){ repIdx={}; const best={};
  frames.forEach((f,k)=>f.regions.forEach(r=>{const a=r.box[2]*r.box[3];
    if(a>(best[r.tid]||-1)){best[r.tid]=a; repIdx[r.tid]=k;}})); }
function snap(idxs){ const fr={}; (idxs||[]).forEach(k=>{ if(frames[k]) fr[k]=JSON.stringify(frames[k].regions); });
  return {fr, c:{...cls}, e:[...edited], sel:selected, ix:idx, cl:[...CLASSES]}; }
function framesWith(tid){ const a=[]; frames.forEach((f,k)=>{ if(f.regions.some(r=>r.tid===tid)) a.push(k); }); return a; }
function restore(s){ for(const k in s.fr){ frames[+k].regions=JSON.parse(s.fr[k]); }
  cls={...s.c}; edited=new Set(s.e); selected=s.sel; idx=s.ix;
  for(const k in s.fr) edited.add(frames[+k].file);   // restored frames may differ from what autosave wrote
  if(s.cl && s.cl.join('\n')!==CLASSES.join('\n')){ CLASSES=[...s.cl]; classesDirty=true; buildAddcls(true); renderClasses(); }
  invalidateTids(); renderList(); go(idx); drawBoxes(); showSel(); refresh(); }
function pushUndoState(s){ undoStack.push(s); if(undoStack.length>40)undoStack.shift(); redoStack=[]; updBtns(); }
function pushUndo(idxs){ pushUndoState(snap(idxs)); }
function undo(){ if(!undoStack.length)return; const s=undoStack.pop();
  redoStack.push(snap(Object.keys(s.fr).map(Number))); restore(s); updBtns(); toast('Undo'); }
function redo(){ if(!redoStack.length)return; const s=redoStack.pop();
  undoStack.push(snap(Object.keys(s.fr).map(Number))); restore(s); updBtns(); toast('Redo'); }
function updBtns(){ document.getElementById('undo').disabled=!undoStack.length; document.getElementById('redo').disabled=!redoStack.length; }
function frameURL(fn){ return '/frame?clip='+encodeURIComponent(clip)+'&f='+encodeURIComponent(fn); }
function tcol(tid){ let h=0; for(const c of tid) h=(h*31+c.charCodeAt(0))%360; return 'hsl('+h+',85%,62%)'; }
// colour by CLASS POSITION in the class list, from a palette of maximally distinct colours
// so neighbouring classes never look alike; past the palette, spread hues by the golden angle.
const PALETTE=['#e6194b','#4363d8','#ffe119','#3cb44b','#f58231','#911eb4','#46f0f0','#f032e6',
  '#bcf60c','#fabebe','#008080','#e6beff','#9a6324','#fffac8','#800000','#aaffc3','#808000',
  '#ffd8b1','#000075','#a9a9a9'];
function clscol(c){ const i=CLASSES.indexOf(c);
  if(i<0) return '#9aa4ad';                                   // not in the list (e.g. NONE)
  return i<PALETTE.length ? PALETTE[i] : 'hsl('+Math.round(i*137.508)%360+',75%,60%)'; }
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
// pick black/white label text by background luminance so labels stay readable on any colour
function textOn(bg){ if(!bg||bg[0]!=='#'||bg.length<7) return '#0b0e11';
  const r=parseInt(bg.slice(1,3),16),g=parseInt(bg.slice(3,5),16),b=parseInt(bg.slice(5,7),16);
  return (0.299*r+0.587*g+0.114*b)/255>0.6 ? '#0b0e11' : '#fff'; }
function boxcol(tid){ return tid===selected?'#ffd23f':clscol(cls[tid]||'NONE'); }
// "@uN" ids mark untracked boxes (no track_id in the JSON). They are drawn dashed and individually
// selectable/deletable, but kept OUT of the object list (they are not tracks). B-side ones get a
// synthetic "@uN" id in clipdata(); A-side (compare) boxes keep the raw "" / "?" — all are untracked.
function isUntracked(t){ return t===''||t==='?'||t==null||(typeof t==='string' && t.startsWith('@u')); }
function shortid(tid){ if(isUntracked(tid)) return 'untracked';
  return tid.includes('#')?'#'+tid.split('#').pop():tid; }
// short class tag for the "123" toggle: its 1-based position in the class list
function clsNum(c){ const i=CLASSES.indexOf(c); return i<0?'?':String(i+1); }
function clsDisp(c){ return numMode?clsNum(c):c; }
function toggleNum(){ numMode=!numMode; const b=document.getElementById('numbtn');
  if(b){ b.classList.toggle('on',numMode); b.textContent=numMode?'Abc':'123'; }
  renderList(); drawBoxes(); if(COMPARE) drawBoxesA(); }
// a box's on-canvas label: untracked boxes show only the class (no id); tracked
// objects show "id · class". Class respects the number toggle.
function boxLabel(tid){ return isUntracked(tid) ? clsDisp(cls[tid]) : (shortid(tid)+' · '+clsDisp(cls[tid])); }
function natCmp(a,b){ // natural sort: compare digit runs numerically so #2 < #10 (no shuffle)
  const ax=String(a).match(/\d+|\D+/g)||[], bx=String(b).match(/\d+|\D+/g)||[];
  for(let i=0;i<Math.min(ax.length,bx.length);i++){
    if(ax[i]===bx[i]) continue;
    if(/^\d/.test(ax[i]) && /^\d/.test(bx[i])) return parseInt(ax[i],10)-parseInt(bx[i],10);
    return ax[i]<bx[i]?-1:1;
  }
  return ax.length-bx.length;
}
function idNum(t){ const m=String(t).match(/(\d+)\D*$/); return m?parseInt(m[1],10):Infinity; } // trailing # number
// order the list by the DISPLAYED number (#0,#1,#2,...,#10,#11 — never lexicographic), natCmp as tiebreak
function idCmp(a,b){ return (idNum(a)-idNum(b)) || natCmp(a,b); }
// cached: scanning 19k frames on every pick was the click-lag culprit. invalidate on any tid-set change.
function presentTids(){ if(_tids) return _tids;
  const s=new Set(); frames.forEach(f=>f.regions.forEach(r=>{ if(!isUntracked(r.tid)) s.add(r.tid); })); _tids=[...s].sort(idCmp); return _tids; }
function invalidateTids(){ _tids=null; }
function scale(){ return img().clientWidth/img().naturalWidth; }
function clampBox(b){ const W=img().naturalWidth,H=img().naturalHeight;
  b[2]=Math.max(4,b[2]); b[3]=Math.max(4,b[3]);
  b[0]=Math.max(0,Math.min(b[0],W-b[2])); b[1]=Math.max(0,Math.min(b[1],H-b[3])); return b; }

function renderList(){
  const list=document.getElementById('list'); list.innerHTML='';
  const allTids=presentTids();
  // populate the class filter from classes present in THIS clip (preserve current selection)
  const present=[...new Set(allTids.map(t=>cls[t]||'NONE'))].sort(natCmp);
  if(classFilter && !present.includes(classFilter)) classFilter='';   // class no longer here -> reset
  const fsel=document.getElementById('clsfilter');
  fsel.innerHTML='<option value="">All classes</option>'+present.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  fsel.value=classFilter;
  // filter ONLY the list; the frame still draws every box (drawBoxes is unaffected)
  const q=(document.getElementById('vsearch').value||'').trim().toLowerCase().replace(/^#/,'');
  const tids=allTids.filter(t=>(!classFilter||(cls[t]||'NONE')===classFilter)
    && (!q||String(t).toLowerCase().includes(q)||shortid(t).toLowerCase().includes(q)));
  document.getElementById('vcount').textContent=tids.length<allTids.length
    ? tids.length+' of '+allTids.length : String(allTids.length);
  // build the whole list as ONE innerHTML string (per-row createElement/appendChild + a closure
  // each was ~1.3s for 7700 objects). Row click is handled by ONE delegated listener (see init).
  // class shown as a compact TEXT label (not a per-row <select> — 7700 selects x18 options was the
  // ~1.3s cost). Click the label to edit it as a dropdown (one select exists at a time).
  let html='';
  for(const tid of tids){
    if(!(tid in cls)) cls[tid]='NONE';
    const s=cls[tid];
    const cl='vrow'+(tid===selected?' sel':'')+(s!==orig[tid]?' changed':'');
    const a=esc(tid);
    const sw=clscol(s);
    html+='<div class="'+cl+'" data-tid="'+a+'"><span class="sw" style="background:'+sw+'"></span>'
        +'<span class="vid">'+esc(shortid(tid))+'</span>'
        +'<span class="vcls" title="click to change class">'+esc(clsDisp(s))+'</span></div>';
  }
  list.innerHTML=html;
}
// turn a class label into a dropdown on click; revert to text after choosing (keeps DOM light)
function editClass(span){
  const row=span.closest('.vrow'); const tid=row.dataset.tid; const s=cls[tid]||'NONE';
  const sel=document.createElement('select');
  sel.innerHTML=CLASSES.map(c=>'<option value="'+esc(c)+'"'+(c===s?' selected':'')+'>'+esc(c)+'</option>').join('');
  sel.onclick=e=>e.stopPropagation();
  let done=false;
  const finish=()=>{ if(done)return; done=true; span.textContent=clsDisp(cls[tid]||'NONE');
    row.classList.toggle('changed',cls[tid]!==orig[tid]); sel.replaceWith(span); };
  sel.onchange=()=>{ classChange(tid,sel.value); finish(); };
  sel.onblur=finish;
  span.replaceWith(sel); sel.focus();
  if(sel.showPicker){ try{ sel.showPicker(); }catch(e){} }
}
function markRows(){ document.querySelectorAll('.vrow').forEach(r=>{const t=r.dataset.tid;
  r.classList.toggle('sel',t===selected); r.classList.toggle('changed',cls[t]!==orig[t]); }); }
// light selection-only update for pick(): move the .sel highlight instead of walking every row
function markSel(){ document.querySelector('.vrow.sel')?.classList.remove('sel');
  if(selected){ const r=document.querySelector(`.vrow[data-tid="${selected.replace(/"/g,'\\"')}"]`); if(r) r.classList.add('sel'); } }
function applyClassFilter(){ classFilter=document.getElementById('clsfilter').value; renderList(); }
function go(i){ idx=Math.max(0,Math.min(frames.length-1,i|0));
  img().src=frameURL(frames[idx].file);
  if(COMPARE) document.getElementById('imgA').src=frameURL(frames[idx].file);
  document.getElementById('slider').value=idx;
  document.getElementById('counter').textContent='Frame '+(idx+1)+' / '+frames.length+'  ·  '+frames[idx].file;
  updateHideBtn(); }
function step(d){ go(idx+d); }
/* ---- zoom (resize the displayed image; boxes recompute from clientWidth so they stay aligned) ---- */
function zoomImg(im){ if(!im)return;
  im.style.width=''; im.style.maxWidth=''; im.style.maxHeight='';   // revert to CSS fit, then measure it
  if(zoom!==1){ const bw=im.clientWidth; im.style.maxWidth='none'; im.style.maxHeight='none'; im.style.width=(bw*zoom)+'px'; } }
function applyZoom(){ zoom=Math.max(0.25,Math.min(6,zoom));
  zoomImg(img()); zoomImg(document.getElementById('imgA'));
  drawBoxes(); if(COMPARE) drawBoxesA();
  const l=document.getElementById('zoomlbl'); if(l) l.textContent=Math.round(zoom*100)+'%'; }
function zoomBy(f){ zoom*=f; applyZoom(); }
function zoomReset(){ zoom=1; applyZoom(); }
/* ---- high-IoU overlap filter: find/step frames where two boxes overlap >= threshold ---- */
function iou(a,b){ const x1=Math.max(a[0],b[0]), y1=Math.max(a[1],b[1]),
  x2=Math.min(a[0]+a[2],b[0]+b[2]), y2=Math.min(a[1]+a[3],b[1]+b[3]);
  const iw=Math.max(0,x2-x1), ih=Math.max(0,y2-y1), inter=iw*ih, uni=a[2]*a[3]+b[2]*b[3]-inter;
  return uni>0?inter/uni:0; }
function iouThresh(){ const v=parseFloat((document.getElementById('ioth')||{}).value); return isFinite(v)?v:0.95; }
function overlapRegions(k){ const rs=frames[k].regions, s=new Set(), th=iouThresh();
  for(let i=0;i<rs.length;i++) for(let j=i+1;j<rs.length;j++)
    if(iou(rs[i].box,rs[j].box)>=th){ s.add(i); s.add(j); } return s; }
function computeOverlaps(){ overlapIdx=[]; frames.forEach((f,k)=>{ if(overlapRegions(k).size) overlapIdx.push(k); }); }
function refreshOverlaps(){ if(!overlapOn) return; computeOverlaps();
  document.getElementById('ovlcount').textContent=overlapIdx.length+' frames'; drawBoxes(); }
function toggleOverlaps(){ overlapOn=!overlapOn;
  document.getElementById('ovlbtn').classList.toggle('on',overlapOn);
  document.getElementById('ovlnav').style.display=overlapOn?'inline-flex':'none';
  if(overlapOn){ computeOverlaps();
    document.getElementById('ovlcount').textContent=overlapIdx.length+' frames';
    toast(overlapIdx.length+' frame(s) with IoU≥'+iouThresh()+' overlaps');
    if(overlapIdx.length && !overlapIdx.includes(idx)) go(overlapIdx[0]); }
  drawBoxes(); }
function gotoOverlap(dir){ if(!overlapIdx.length){ toast('no overlaps'); return; }
  let nx = dir>0 ? overlapIdx.find(k=>k>idx) : null;
  if(dir<0){ const pr=overlapIdx.filter(k=>k<idx); nx=pr.length?pr[pr.length-1]:null; }
  if(nx==null) nx = dir>0?overlapIdx[0]:overlapIdx[overlapIdx.length-1];
  go(nx); }
/* ---- hide boxes on a frame (view only) ---- */
function isHidden(){ return frames[idx] && hidden.has(frames[idx].file); }
function updateHideBtn(){ const b=document.getElementById('hidebtn'); if(!b)return;
  const h=isHidden(); b.querySelector('.lbl').textContent=h?'Show boxes':'Hide boxes'; b.classList.toggle('on',h);
  document.getElementById('wrap').classList.toggle('boxeshidden',h); }
function toggleHide(){ if(!frames[idx])return;
  const f=frames[idx].file;
  if(hidden.has(f)) hidden.delete(f);
  else { hidden.add(f); if(addMode) toggleAdd(); }   // turn off Add when hiding — can't draw while hidden
  updateHideBtn(); drawBoxes(); if(COMPARE) drawBoxesA();
  toast(isHidden()?'Boxes hidden on this frame':'Boxes shown'); }
function drawBoxes(){
  const w=document.getElementById('wrap'); w.querySelectorAll('.vbox:not(.preview)').forEach(e=>e.remove());
  if(isHidden()) return;                 // boxes hidden on this frame: draw nothing (positions untouched)
  const s=scale(), df=COMPARE?frameDiff(idx):null;
  const ovl=overlapOn?overlapRegions(idx):null;      // region indices in a high-IoU overlapping pair
  frames[idx].regions.forEach((r,ri)=>{
    const isSel=r.tid===selected, hot=df&&df.bChanged.has(ri), untr=isUntracked(r.tid), isOvl=ovl&&ovl.has(ri);
    const [x,y,ww,hh]=r.box, c=hot?HOT:boxcol(r.tid);
    const d=document.createElement('div'); d.className='vbox'+(isSel?' sel':'')+(untr?' untracked':''); d.dataset.ri=ri;
    d.style.cssText+=`left:${x*s}px;top:${y*s}px;width:${ww*s}px;height:${hh*s}px;border-color:${c}`
      +(untr?';border-style:dashed':'')
      +(isOvl?';border-color:#ff3b3b;border-width:4px;box-shadow:0 0 0 2px #ff3b3b55;z-index:4':'')
      +(hot?';border-width:4px;opacity:1;z-index:3':(df&&!isSel?';opacity:.22':''));
    d.innerHTML=`<span class=vlabel style="background:${c};color:${textOn(c)}">${esc(boxLabel(r.tid))}</span>`;
    if(isSel){ for(const cn of ['nw','ne','sw','se']){ const hd=document.createElement('div');
      hd.className='h '+cn; hd.onmousedown=(e)=>startDrag(e,ri,cn); d.appendChild(hd); } }
    // Single click+drag: if the cursor is inside the ALREADY-selected box, MOVE it (don't reselect —
    // this is the fix for "small box inside a large one kept re-selecting the large box"). Otherwise
    // select the front-most box here and move it. DOUBLE-click steps to the box BEHIND, so you can
    // reach a small box sitting inside a larger one; then a normal click+drag moves it.
    d.onmousedown=(e)=>{ if(addMode)return; if(e.target.classList.contains('h'))return;
      e.stopPropagation();
      const si=selectedIdx();
      if(si>=0 && pointInRegion(e,si)){ startDrag(e,si,'move'); return; }
      const ci=frontAt(e); if(ci>=0){ pick(frames[idx].regions[ci].tid,false); startDrag(e,ci,'move'); } };
    d.ondblclick=(e)=>{ if(addMode)return; e.stopPropagation();
      const ci=cycleAt(e);
      if(ci>=0){ const tid=frames[idx].regions[ci].tid; pick(tid,false);
        toast('Selected '+shortid(tid)+' · '+cls[tid]+' · drag to move it'); } };
    w.appendChild(d);
  });
}
// region indices whose box contains the cursor, front-most first (higher array index paints on top)
function regionsAt(e){
  const r=img().getBoundingClientRect(), sc=img().naturalWidth/img().clientWidth;
  const px=(e.clientX-r.left)*sc, py=(e.clientY-r.top)*sc, cand=[];
  frames[idx].regions.forEach((rg,i)=>{ const [x,y,w,h]=rg.box;
    if(px>=x&&px<=x+w&&py>=y&&py<=y+h) cand.push(i); });
  cand.sort((a,b)=>b-a);                          // front (top-most) first
  return cand;
}
function frontAt(e){ const c=regionsAt(e); return c.length?c[0]:-1; }          // topmost box, no cycling
function cycleAt(e){ const c=regionsAt(e); if(!c.length) return -1;            // step to the box BEHIND
  const cur=c.findIndex(i=>frames[idx].regions[i].tid===selected); return c[(cur+1)%c.length]; }
function pointInRegion(e,i){ const rg=frames[idx].regions[i]; if(!rg) return false;
  const r=img().getBoundingClientRect(), sc=img().naturalWidth/img().clientWidth;
  const px=(e.clientX-r.left)*sc, py=(e.clientY-r.top)*sc, [x,y,w,h]=rg.box;
  return px>=x&&px<=x+w&&py>=y&&py<=y+h; }
function selectedIdx(){ return selected!=null ? frames[idx].regions.findIndex(r=>r.tid===selected) : -1; }
/* ---- compare mode: A (before) panel + frame diffing ---- */
const HOT='#ff3bce';   // highlight color for a box that changed between A and B
// Compare A (before) vs B (after) on frame k — PRESENCE-ONLY diff: highlight a box ONLY when the
// object exists in one file but not the other (added in B, or removed from A). A matched object
// present in BOTH is NOT highlighted, even if its class or box was edited.
//   • TRACKED objects (have a track_id) match by track_id.
//   • UNTRACKED objects (no track_id) have no stable id, so they match by exact class+geometry
//     (multiset): an identical box in both = present in both; a box only in one file = highlighted.
// Returns index sets for each panel (aChanged / bChanged) + added/removed counts.
function _sig(cl,b){ return cl+'|'+b[0]+','+b[1]+','+b[2]+','+b[3]; }
function frameDiff(k){
  const A=frames[k].a||[], B=frames[k].regions;
  const aChanged=new Set(), bChanged=new Set();
  let add=0, del=0;
  // ---- tracked: present-in-both by track_id => not a difference ----
  const aTids=new Set(), bTids=new Set();
  A.forEach(r=>{ if(!isUntracked(r.tid)) aTids.add(r.tid); });
  B.forEach(r=>{ if(!isUntracked(r.tid)) bTids.add(r.tid); });
  B.forEach((r,i)=>{ if(!isUntracked(r.tid) && !aTids.has(r.tid)){ bChanged.add(i); add++; } });  // only in B
  A.forEach((r,i)=>{ if(!isUntracked(r.tid) && !bTids.has(r.tid)){ aChanged.add(i); del++; } });  // only in A
  // ---- untracked: match by class+geometry (multiset) ----
  const pool={};   // sig -> [aIdx, ...] still available to match
  A.forEach((r,i)=>{ if(isUntracked(r.tid)){ const key=_sig(r.cls,r.box); (pool[key]=pool[key]||[]).push(i); } });
  B.forEach((r,i)=>{ if(isUntracked(r.tid)){
    const key=_sig(cls[r.tid]||'NONE', r.box);
    if(pool[key] && pool[key].length){ pool[key].shift(); }   // identical box exists in A -> present in both
    else { bChanged.add(i); add++; } } });                    // no match -> only in B -> highlight
  for(const key in pool) for(const ai of pool[key]){ aChanged.add(ai); del++; }   // leftover A -> only in A
  return {aChanged, bChanged, changed:(aChanged.size||bChanged.size)>0, add, del};
}
function drawBoxesA(){
  const w=document.getElementById('wrapA'); if(!w)return;
  w.querySelectorAll('.vbox').forEach(e=>e.remove());
  if(isHidden()) return;                 // keep A/B panels in sync when boxes are hidden
  const imA=document.getElementById('imgA'); if(!imA.naturalWidth)return;
  const s=imA.clientWidth/imA.naturalWidth, df=frameDiff(idx);
  (frames[idx].a||[]).forEach((r,i)=>{
    const untr=isUntracked(r.tid), [x,y,ww,hh]=r.box, hot=df.aChanged.has(i), c=hot?HOT:clscol(r.cls);
    const d=document.createElement('div'); d.className='vbox'+(untr?' untracked':'');
    d.style.cssText+=`left:${x*s}px;top:${y*s}px;width:${ww*s}px;height:${hh*s}px;border-color:${c};cursor:default;`
      +(untr?'border-style:dashed;':'')
      +(hot?'border-width:4px;opacity:1;z-index:3':'opacity:.22');
    const lbl=isUntracked(r.tid)?clsDisp(r.cls):(shortid(r.tid)+' · '+clsDisp(r.cls));
    d.innerHTML=`<span class=vlabel style="background:${c};color:${textOn(c)}">${esc(lbl)}</span>`;
    w.appendChild(d);
  });
}
function frameChanged(k){ return frameDiff(k).changed; }
function diffSummary(k){
  const d=frameDiff(k), p=[];
  if(d.add)p.push('+'+d.add+' added'); if(d.del)p.push('−'+d.del+' removed');
  return p.join(' ')||'changed';
}
function computeDiff(){ changedIdx=[]; for(let k=0;k<frames.length;k++) if(frameChanged(k)) changedIdx.push(k); renderDiff(); }
function renderDiff(){
  document.getElementById('diffn').textContent='('+changedIdx.length+')';
  document.getElementById('diffcount').textContent=changedIdx.length+' changed';
  const dl=document.getElementById('difflist'); dl.innerHTML='';
  changedIdx.forEach(k=>{ const row=document.createElement('div'); row.className='vrow'; row.style.padding='6px 8px';
    row.innerHTML=`<span class=vid>#${frames[k].f}</span><span class=muted style="font-size:.72rem">${diffSummary(k)}</span>`;
    row.onclick=()=>go(k); dl.appendChild(row); });
}
function gotoDiff(dir){
  if(!changedIdx.length){toast('no differences');return;}
  let nx;
  if(dir>0) nx=changedIdx.find(k=>k>idx);
  else { const pr=changedIdx.filter(k=>k<idx); nx=pr.length?pr[pr.length-1]:null; }
  if(nx==null) nx=dir>0?changedIdx[0]:changedIdx[changedIdx.length-1];  // wrap around
  go(nx);
}
function pick(tid, jump=true){
  selected=tid; markSel(); drawBoxes(); showSel();
  const row=document.querySelector(`.vrow[data-tid="${tid}"]`); if(row) row.scrollIntoView({block:'nearest'});
  if(jump && frames[idx].regions.every(r=>r.tid!==tid) && repIdx[tid]!=null) go(repIdx[tid]);
}
function showSel(){
  const bar=document.getElementById('selbar'); if(!selected){bar.style.display='none';return;}
  bar.style.display='flex'; document.getElementById('selid').textContent=shortid(selected);
  // don't build the (potentially thousands-long) merge dropdown here — that made every click lag.
  // reset it to just the placeholder and mark it stale; buildIdOpts() fills it on first open.
  document.getElementById('idsel').innerHTML='<option value="">(merge into… )</option>';
  idselStale=true;
  const inp=document.getElementById('idinput'); if(inp) inp.value='';
}
function buildIdOpts(){ const sel=document.getElementById('idsel');
  const others=presentTids().filter(t=>t!==selected);
  sel.innerHTML='<option value="">(keep own id)</option>'+
    others.map(t=>`<option value="${esc(t)}">merge into ${esc(shortid(t))}</option>`).join('');
  idselStale=false;
}
function classChange(tid,val){
  // an untracked box stores its class per box, so its frame must be rewritten on save
  const fr=isUntracked(tid)?framesWith(tid):[];
  pushUndo(fr); cls[tid]=val; fr.forEach(k=>edited.add(frames[k].file));
  const row=document.querySelector(`.vrow[data-tid="${tid.replace(/"/g,'\\"')}"]`);
  if(row){ row.querySelector('.sw').style.background=clscol(val); const v=row.querySelector('.vcls'); if(v) v.textContent=clsDisp(val); }
  markRows(); drawBoxes(); refresh(); }
// hotkey 1..9: re-class the selected object everywhere, or (nothing selected) pick the new-box class
function hotkeyClass(n){ const c=CLASSES[n-1]; if(c==null){ toast('No class '+n+' (open Classes to add one)'); return; }
  if(selected){ if(cls[selected]===c) return;
    classChange(selected,c);
    toast(shortid(selected)+' → '+c+(isUntracked(selected)?'':' (all frames)')); }
  else { document.getElementById('addcls').value=c; toast('New boxes: '+c); } }
// resolve a typed id to a full track_id: accepts the full id, '#835', or '835' (short/number).
function resolveTid(s){ s=String(s||'').trim(); if(!s) return null;
  const all=presentTids();
  if(all.includes(s)) return s;
  const num=s.replace(/^#/,'');
  const hits=all.filter(t=>shortid(t)===('#'+num) || String(idNum(t))===num);
  if(hits.length===1) return hits[0];
  if(hits.length>1)  return 'AMBIG';
  return null;
}
function doMerge(to){
  pushUndo(framesWith(selected));   // only the frames where the merged-away id appears
  frames.forEach(f=>{ let hit=false; f.regions.forEach(r=>{ if(r.tid===selected){r.tid=to;hit=true;} }); if(hit)edited.add(f.file); });
  selected=to; invalidateTids(); renderList(); drawBoxes(); showSel(); refresh();
  const inp=document.getElementById('idinput'); if(inp) inp.value='';
  toast('Merged into '+shortid(to)); }
function confirmMerge(to){
  if(!selected||!to||to===selected) return false;
  return confirm('Merge '+shortid(selected)+'  →  '+shortid(to)+' ?\n\n'
    +'Every box of '+shortid(selected)+' becomes '+shortid(to)+' across all frames.\n'
    +'(Undo with Ctrl+Z if this was a mistake.)'); }
function reassignId(){ const sel=document.getElementById('idsel'); const to=sel.value;
  if(!to||to===selected){ return; }
  if(confirmMerge(to)) doMerge(to); else sel.value='';   // note + confirm before merging
}
function mergeTyped(){ if(!selected){ toast('Select an object first'); return; }
  const raw=document.getElementById('idinput').value;
  const to=resolveTid(raw);
  if(to===null){ toast('No object with id "'+raw.trim()+'" on this dataset'); return; }
  if(to==='AMBIG'){ toast('"'+raw.trim()+'" matches more than one — type the full id'); return; }
  if(to===selected){ toast('That is the selected object itself'); return; }
  if(confirmMerge(to)) doMerge(to);
}
function dirtyCount(){ return Object.keys(cls).filter(t=>cls[t]!==orig[t]).length + edited.size + (classesDirty?1:0); }
function refresh(){ const n=dirtyCount(); document.getElementById('save').disabled=!n;
  document.getElementById('dirty').textContent = n ? (saving?'saving…':'auto-saving…') : (outName?'all changes saved':'');
  if(n) scheduleAutosave();      // any pending edit triggers a debounced write to the edited file
}

/* ---- move / resize ---- */
function startDrag(e,ri,mode){ e.preventDefault(); e.stopPropagation();
  drag={ri,mode,sx:e.clientX,sy:e.clientY,box0:[...frames[idx].regions[ri].box],s:img().naturalWidth/img().clientWidth,pre:snap([idx]),moved:false}; }
addEventListener('mousemove',e=>{ if(!drag)return; drag.moved=true;
  const dx=(e.clientX-drag.sx)*drag.s, dy=(e.clientY-drag.sy)*drag.s; let [x,y,w,h]=drag.box0;
  if(drag.mode==='move'){ x+=dx; y+=dy; }
  else if(drag.mode==='se'){ w+=dx; h+=dy; }
  else if(drag.mode==='sw'){ x+=dx; w-=dx; h+=dy; }
  else if(drag.mode==='ne'){ y+=dy; w+=dx; h-=dy; }
  else if(drag.mode==='nw'){ x+=dx; y+=dy; w-=dx; h-=dy; }
  frames[idx].regions[drag.ri].box=clampBox([Math.round(x),Math.round(y),Math.round(w),Math.round(h)]); drawBoxes(); });
addEventListener('mouseup',()=>{ if(drag){ if(drag.moved){ pushUndoState(drag.pre); edited.add(frames[idx].file); refresh(); } drag=null; } });

/* ---- add / delete ---- */
function toggleAdd(){
  if(!addMode && isHidden()){ toast('Boxes are hidden on this frame — show them to draw'); return; }
  addMode=!addMode;
  document.getElementById('addbtn').classList.toggle('on',addMode);
  document.getElementById('wrap').classList.toggle('adding',addMode); }
function deselect(){ if(!selected)return; selected=null; markSel(); showSel(); drawBoxes(); }
// click ANYWHERE that isn't a box, a control, or the object list -> unselect the current box.
// (box/handle mousedown call stopPropagation, so a click ON a box never reaches this.)
addEventListener('mousedown',e=>{ if(!selected||addMode)return;
  if(e.target.closest('.vbox,.vrow,.vcls,button,select,input,textarea,#selbar,#loader,#browser,#classdlg,#trackdlg,#helpdlg,#side'))return;
  deselect(); });
const wrap=document.getElementById('wrap');
wrap.addEventListener('mousedown',e=>{ if(!addMode||isHidden())return; e.preventDefault();
  const r=img().getBoundingClientRect(); draw={ox:e.clientX-r.left,oy:e.clientY-r.top,r};
  const p=document.createElement('div'); p.className='vbox preview'; p.id='prev'; wrap.appendChild(p); });
addEventListener('mousemove',e=>{ if(!draw)return; const p=document.getElementById('prev'); if(!p)return;
  const x=e.clientX-draw.r.left,y=e.clientY-draw.r.top;
  p.style.cssText=`position:absolute;left:${Math.min(x,draw.ox)}px;top:${Math.min(y,draw.oy)}px;width:${Math.abs(x-draw.ox)}px;height:${Math.abs(y-draw.oy)}px`; });
addEventListener('mouseup',e=>{ if(!draw)return; const p=document.getElementById('prev'); if(p)p.remove();
  const s=img().naturalWidth/img().clientWidth;
  const x=Math.min(e.clientX-draw.r.left,draw.ox), y=Math.min(e.clientY-draw.r.top,draw.oy);
  const w=Math.abs((e.clientX-draw.r.left)-draw.ox), h=Math.abs((e.clientY-draw.r.top)-draw.oy); draw=null;
  if(w<5||h<5)return;
  pushUndo([idx]);
  const box=clampBox([Math.round(x*s),Math.round(y*s),Math.round(w*s),Math.round(h*s)]);
  const ncls=document.getElementById('addcls').value||'NONE';
  // "untracked" boxes get no track_id (saved empty, dashed, not in the object list); others a "new#N" id
  const tid = document.getElementById('adduntr').checked ? ('@u'+(newU++)) : ('new#'+(newN++));
  cls[tid]=ncls;
  frames[idx].regions.push({tid,box}); edited.add(frames[idx].file);
  selected=tid; invalidateTids(); renderList(); drawBoxes(); showSel(); refresh(); toast('Added '+ncls+' box'); });
function deleteSelected(){ if(!selected)return;
  const regs=frames[idx].regions, i=regs.findIndex(r=>r.tid===selected);
  if(i<0){ toast('This object has no box on this frame'); return; }
  pushUndo([idx]); regs.splice(i,1); edited.add(frames[idx].file); invalidateTids(); renderList(); drawBoxes(); showSel(); refresh(); toast('Deleted box on this frame'); }
// delete an object ENTIRELY — every box of this id across all frames (undoable via the same snapshot)
function deleteTrack(){ if(!selected)return;
  const tid=selected, aff=framesWith(tid);
  if(!aff.length){ toast('This object has no boxes'); return; }
  if(!confirm('Delete object '+shortid(tid)+' from ALL '+aff.length+' frame(s)?\nThis removes every box of '+shortid(tid)+'. (Ctrl+Z to undo.)')) return;
  pushUndo(aff);                                  // snapshot every affected frame -> full undo/redo
  aff.forEach(k=>{ frames[k].regions=frames[k].regions.filter(r=>r.tid!==tid); edited.add(frames[k].file); });
  selected=null; invalidateTids(); renderList(); drawBoxes(); showSel(); refresh();
  toast('Deleted object '+shortid(tid)+' from '+aff.length+' frame(s)'); }
addEventListener('keydown',e=>{
  const t=e.target.tagName;                       // never hijack keys while typing / in a dropdown
  if(t==='INPUT'||t==='SELECT'||t==='TEXTAREA'||e.target.isContentEditable){
    if(e.target.id==='idinput'&&e.key==='Enter'){ e.preventDefault(); mergeTyped(); }
    if(e.target.id==='newcls'&&e.key==='Enter'){ e.preventDefault(); addClass(); }
    return;
  }
  const z=(e.key==='z'||e.key==='Z'), y=(e.key==='y'||e.key==='Y');
  if((e.ctrlKey||e.metaKey)&&z&&!e.shiftKey){ e.preventDefault(); undo(); return; }
  if((e.ctrlKey||e.metaKey)&&(y||(z&&e.shiftKey))){ e.preventDefault(); redo(); return; }
  if(e.key==='?'){ e.preventDefault(); openHelp(); return; }
  if(e.key==='Escape'&&document.getElementById('helpdlg').style.display==='flex'){ closeHelp(); return; }
  if(e.key==='Escape'&&document.getElementById('classdlg').style.display==='flex'){ closeClasses(); return; }
  if(e.key==='Escape'&&document.getElementById('trackdlg').style.display==='flex'){ closeTracker(); return; }
  if(e.key==='Escape'&&selected){ deselect(); return; }   // Escape also unselects
  if(e.key==='+'||e.key==='='){ e.preventDefault(); zoomBy(1.25); return; }   // zoom in
  if(e.key==='-'||e.key==='_'){ e.preventDefault(); zoomBy(1/1.25); return; } // zoom out
  if(e.key==='0'){ e.preventDefault(); zoomReset(); return; }                 // reset zoom
  if(/^[1-9]$/.test(e.key)&&!e.ctrlKey&&!e.metaKey&&!e.altKey){ e.preventDefault(); hotkeyClass(+e.key); return; }
  if(e.key==='ArrowLeft')step(-1); else if(e.key==='ArrowRight')step(1);
  else if((e.key==='Delete'||e.key==='Backspace')&&selected){e.preventDefault(); e.shiftKey?deleteTrack():deleteSelected();} });
addEventListener('resize',()=>{ if(!drag&&!draw){ if(zoom!==1) applyZoom(); else drawBoxes(); } });
// mouse-wheel over the image zooms, ANCHORED at the cursor (scroll up = in, down = out).
document.getElementById('stages').addEventListener('wheel',e=>{
  const st=e.target.closest('.stage'); if(!st)return;
  const im=st.querySelector('img'); if(!im||!im.naturalWidth)return;
  e.preventDefault();
  const r0=im.getBoundingClientRect(), sc0=im.clientWidth/im.naturalWidth;   // point under cursor (natural coords)
  const nx=(e.clientX-r0.left)/sc0, ny=(e.clientY-r0.top)/sc0;
  zoom=Math.max(0.25,Math.min(6, zoom*(e.deltaY<0?1.15:1/1.15))); applyZoom();
  const sc1=im.clientWidth/im.naturalWidth, sr=st.getBoundingClientRect();   // keep that point under the cursor
  st.scrollLeft=nx*sc1-(e.clientX-sr.left);
  st.scrollTop =ny*sc1-(e.clientY-sr.top);
}, {passive:false});

/* ---- project loader + server-side file browser ---- */
let loaderMode='single', browseTarget=null, browseFolder=false, curDir='', curParent='';
function val(id){ return document.getElementById(id).value.trim(); }
function openLoader(){ document.getElementById('loader').style.display='flex'; setMode(loaderMode); }
function closeLoader(){ document.getElementById('loader').style.display='none'; }
function setMode(m){ loaderMode=m;
  document.getElementById('m_single').className=m==='single'?'on':'ghost';
  document.getElementById('m_compare').className=m==='compare'?'on':'ghost';
  document.getElementById('row_jsonA').style.display=m==='compare'?'block':'none';
  document.getElementById('btnCheck').style.display=m==='compare'?'inline-block':'none';
  document.getElementById('lab_jsonB').textContent=m==='compare'?'Corrected JSON (after) — B':'Annotation JSON';
  document.getElementById('f_report').textContent=''; }
async function browse(target,wantFolder){ browseTarget=target; browseFolder=wantFolder;
  document.getElementById('b_usefolder').style.display=wantFolder?'inline-block':'none';
  document.getElementById('browser').style.display='flex'; await ls(val(target)||curDir||''); }
function closeBrowser(){ document.getElementById('browser').style.display='none'; }
// join a browser dir + child name. The server returns clean, OS-native paths on the next ls, so a
// mixed "/" here is fine (Python's os.path accepts it on Windows too). For the virtual drive root the
// entries are already absolute (e.g. "C:\"), so we navigate straight to them.
function joinPath(base,name,absolute){
  if(absolute) return name;
  const sep = base.indexOf('\\')>=0 ? '\\' : '/';         // keep the OS separator the server sent
  return base.replace(/[\\/]+$/,'') + sep + name;
}
async function ls(path){ const d=await (await fetch('/ls?path='+encodeURIComponent(path))).json();
  curDir=d.path; curParent=d.parent; const abs=!!d.absolute_entries;
  document.getElementById('b_path').textContent = d.path==='::drives::' ? 'This PC (pick a drive)' : d.path;
  const L=document.getElementById('b_list'); L.innerHTML='';
  const tag=(d.has_images?' · has images/':(d.has_frames?' · has frames/':''));
  if(tag){ const h=document.createElement('div'); h.className='muted'; h.style.padding='6px 10px'; h.textContent='(this folder'+tag+')'; L.appendChild(h); }
  (d.dirs||[]).forEach(n=>{ const b=document.createElement('div'); b.className='vrow'; b.style.padding='7px 10px';
    b.textContent=(abs?'💽 ':'📁 ')+n; b.onclick=()=>ls(joinPath(d.path,n,abs)); L.appendChild(b); });
  (d.jsons||[]).forEach(n=>{ const b=document.createElement('div'); b.className='vrow'; b.style.padding='7px 10px';
    b.textContent='📄 '+n; b.onclick=()=>pickJson(joinPath(d.path,n,abs)); L.appendChild(b); }); }
function lsUp(){ ls(curParent||curDir); }   // parent computed server-side (correct on Windows too)
function pickJson(fp){ if(browseFolder){ return; } document.getElementById(browseTarget).value=fp; closeBrowser(); }
function useFolder(){ document.getElementById(browseTarget).value=curDir; closeBrowser(); }
function fmtReport(rep){
  if(rep.errors&&rep.errors.length) return '✗ '+rep.errors.join('\n✗ ');
  const i=rep.info||{}; let s='✓ '+i.common+' common frames';
  if(i.only_a||i.only_b) s+='  (A-only '+i.only_a+', B-only '+i.only_b+' — compared on the common set)';
  if(rep.warnings&&rep.warnings.length) s+='\n⚠ '+rep.warnings.join('\n⚠ ');
  return s; }
async function doCheck(){ const r=document.getElementById('f_report');
  const rep=await (await fetch('/validate',{method:'POST',body:JSON.stringify({
    json_a:val('f_jsonA'),json_b:val('f_jsonB'),frames_dir:val('f_frames')})})).json();
  r.textContent=fmtReport(rep); r.style.color=rep.ok?'var(--good)':'var(--bad)'; return rep; }
// last-ditch flush if the tab is closed within the autosave debounce window: sendBeacon survives unload
addEventListener('beforeunload',()=>{ if(!outName || !dirtyCount()) return;
  const edits={}; edited.forEach(fn=>{ const fr=frames.find(f=>f.file===fn);
    if(fr) edits[fn]=fr.regions.map(r=>({tid:r.tid,box:r.box,x:r.x})); });
  try{ navigator.sendBeacon('/save',
    new Blob([JSON.stringify({clip:clip,cls:cls,edits:edits,classes:CLASSES})],{type:'application/json'})); }catch(e){} });
async function doOpen(){
  const r=document.getElementById('f_report');
  if(!val('f_jsonB')){ r.style.color='var(--bad)'; r.textContent='✗ pick the annotation JSON'; return; }
  if(loaderMode==='compare' && !val('f_jsonA')){ r.style.color='var(--bad)'; r.textContent='✗ pick the original (A) JSON to compare against'; return; }
  const body={ json:val('f_jsonB'), frames_dir:val('f_frames') };
  if(loaderMode==='compare') body.compare_json=val('f_jsonA');
  const res=await (await fetch('/open',{method:'POST',body:JSON.stringify(body)})).json();
  if(!res.ok){ r.style.color='var(--bad)'; r.textContent = res.error ? ('✗ '+res.error) : fmtReport(res.report||{errors:['open failed']}); return; }
  const sel=document.getElementById('clipsel'); sel.innerHTML='<option>'+esc(res.name)+'</option>'; sel.value=res.name; clip=res.name;
  closeLoader(); await load(0,null);
}

/* ---- class manager: add / rename / delete classes (saved into the project JSON) ---- */
function classUsage(){ const n={}, seen=new Set();      // class -> number of objects (tracks + untracked boxes)
  frames.forEach(f=>f.regions.forEach(r=>{ if(seen.has(r.tid))return; seen.add(r.tid);
    const c=cls[r.tid]||'NONE'; n[c]=(n[c]||0)+1; })); return n; }
function openClasses(){ document.getElementById('classdlg').style.display='flex'; renderClasses();
  document.getElementById('newcls').focus(); }
function closeClasses(){ document.getElementById('classdlg').style.display='none'; }
function renderClasses(){ const L=document.getElementById('clslist'); if(!L)return;
  const use=classUsage();
  L.innerHTML=CLASSES.map((c,i)=>{ const n=use[c]||0;
    return '<div class="crow" data-i="'+i+'"><span class="sw" style="background:'+clscol(c)+'"></span>'
      +'<kbd title="hotkey">'+(i<9?i+1:'')+'</kbd>'
      +'<input class="cname" value="'+esc(c)+'" title="edit, then press Enter to rename">'
      +'<span class="muted cuse">'+n+' object'+(n===1?'':'s')+'</span>'
      +'<button class="ghost small" data-act="up" title="move up"'+(i?'':' disabled')+'>↑</button>'
      +'<button class="ghost small danger" data-act="del" title="delete class">✕</button></div>'; }).join('')
    || '<div class="muted" style="padding:10px">No classes yet. Add one below.</div>';
}
function classesChanged(msg){ classesDirty=true; invalidateTids(); buildAddcls(true); renderClasses();
  renderList(); drawBoxes(); if(COMPARE) drawBoxesA(); refresh(); if(msg) toast(msg); }
function addClass(){ const inp=document.getElementById('newcls'); const name=inp.value.trim();
  if(!name) return;
  if(name==='NONE'){ toast('"NONE" is reserved for unlabeled objects'); return; }
  if(CLASSES.includes(name)){ toast('"'+name+'" already exists'); return; }
  pushUndo([]); CLASSES.push(name); inp.value=''; classesChanged('Added class '+name); }
// every object of class `from` becomes `to`. Untracked boxes carry their class per box, so their
// frames are marked edited too (tracked objects are re-classed on save from the per-id map).
function reclassAll(from,to){ const touched=[];
  for(const t in cls) if(cls[t]===from){ cls[t]=to; if(isUntracked(t)) touched.push(t); }
  if(touched.length){ const s=new Set(touched);
    frames.forEach(f=>{ if(f.regions.some(r=>s.has(r.tid))) edited.add(f.file); }); } }
function framesWithUntrackedOf(c){ const a=[]; frames.forEach((f,k)=>{
  if(f.regions.some(r=>isUntracked(r.tid)&&cls[r.tid]===c)) a.push(k); }); return a; }
function renameClass(i,name){ const old=CLASSES[i]; name=name.trim();
  if(!name||name===old){ renderClasses(); return; }
  if(name==='NONE'){ toast('"NONE" is reserved'); renderClasses(); return; }
  if(CLASSES.includes(name)){
    if(!confirm('Merge class "'+old+'" into existing class "'+name+'"?\nEvery "'+old+'" object becomes "'+name+'".')){ renderClasses(); return; }
    pushUndo(framesWithUntrackedOf(old)); reclassAll(old,name); CLASSES.splice(i,1);
    classesChanged('Merged '+old+' into '+name); return; }
  pushUndo(framesWithUntrackedOf(old)); reclassAll(old,name); CLASSES[i]=name;
  classesChanged('Renamed '+old+' to '+name); }
function deleteClass(i){ const c=CLASSES[i], n=classUsage()[c]||0;
  if(n){ const others=CLASSES.filter(x=>x!==c);
    const to=prompt(n+' object(s) use "'+c+'". Move them to which class?\n'
      +'Type one of: '+others.join(', ')+'\n(or leave blank to mark them NONE / unlabeled)', others[0]||'');
    if(to===null) return;
    const dest=to.trim()||'NONE';
    if(dest!=='NONE' && !others.includes(dest)){ toast('No class named "'+dest+'"'); return; }
    pushUndo(framesWithUntrackedOf(c)); reclassAll(c,dest); }
  else pushUndo([]);
  CLASSES.splice(i,1); classesChanged('Deleted class '+c); }
function moveClassUp(i){ if(i<1)return; pushUndo([]);
  [CLASSES[i-1],CLASSES[i]]=[CLASSES[i],CLASSES[i-1]]; classesChanged(); }
document.getElementById('clslist').addEventListener('click',e=>{
  const b=e.target.closest('button'); if(!b)return; const i=+b.closest('.crow').dataset.i;
  if(b.dataset.act==='del') deleteClass(i); else if(b.dataset.act==='up') moveClassUp(i); });
document.getElementById('clslist').addEventListener('keydown',e=>{
  if(e.key==='Enter'&&e.target.classList.contains('cname')){ e.preventDefault(); e.target.blur(); } });
document.getElementById('clslist').addEventListener('change',e=>{
  if(e.target.classList.contains('cname')) renameClass(+e.target.closest('.crow').dataset.i, e.target.value); });

/* ---- tracker: link boxes into tracks with ByteTrack (runs in the local Python server) ---- */
function openTracker(){ document.getElementById('trackdlg').style.display='flex';
  document.getElementById('trkstatus').textContent=''; }
function closeTracker(){ document.getElementById('trackdlg').style.display='none'; }
function num(id,d){ const v=parseFloat(document.getElementById(id).value); return isFinite(v)?v:d; }
async function runTracker(){
  const scope=document.querySelector('input[name=trkscope]:checked').value;
  const inScope=r=>scope==='all'||isUntracked(r.tid);
  const payload=frames.map(f=>({file:f.file, regions:f.regions.filter(inScope)
    .map(r=>({box:r.box, score:r.s==null?null:r.s, cls:cls[r.tid]||'NONE'}))}));
  const nBoxes=payload.reduce((a,f)=>a+f.regions.length,0);
  const st=document.getElementById('trkstatus');
  if(!nBoxes){ st.textContent=scope==='all'?'There are no boxes to track.':'There are no untracked boxes.'; return; }
  // new ids must not collide with ids that are kept
  let prefix='trk#';
  if(scope!=='all'){ const kept=presentTids(); for(let n=2; kept.some(t=>String(t).startsWith(prefix)); n++) prefix='trk'+n+'#'; }
  const btn=document.getElementById('trkrun'); btn.disabled=true;
  st.style.color=''; st.textContent='Tracking '+nBoxes+' boxes…';
  let res;
  try{ res=await (await fetch('/track',{method:'POST',body:JSON.stringify({frames:payload,id_prefix:prefix,
      params:{match_iou:num('trkiou',0.2), track_buffer:Math.round(num('trkbuf',30)),
              high_thresh:num('trkhigh',0.5), class_aware:document.getElementById('trkcls').checked}})})).json(); }
  catch(e){ res={ok:false,error:String(e)}; }
  btn.disabled=false;
  if(!res.ok){ st.style.color='var(--bad)'; st.textContent='Tracking failed: '+res.error; return; }
  pushUndo(frames.map((_,k)=>k));                     // one undo step restores every frame
  frames.forEach((f,k)=>{ const ids=res.ids[k]; let j=0;
    f.regions.forEach(r=>{ if(inScope(r)) r.tid=ids[j++]; }); edited.add(f.file); });
  for(const t in res.classes) cls[t]=res.classes[t];
  selected=null; invalidateTids(); computeRepIdx(); renderList(); drawBoxes(); showSel(); refresh();
  if(COMPARE) computeDiff();
  closeTracker();
  toast('Tracked '+nBoxes+' boxes into '+res.tracks+' tracks'+(res.sequences>1?' across '+res.sequences+' sequences':'')+' · Ctrl+Z to undo');
}

// Persist to the EDITED file (never the original). Autosave calls this silently; the Save button
// passes announce=true for a toast. The client already holds the authoritative state, so after a
// successful write we just reset the baseline (orig=cls, clear edited) instead of reloading — the
// view is untouched and dirtyCount() goes to 0.
async function doSave(announce){
  if(saving){ saveAgain=true; return; }             // coalesce overlapping saves
  if(!dirtyCount() && !announce) return;
  saving=true;
  const snapCls={...cls};                            // capture the baseline we're about to persist
  const snapEdited=new Set(edited);
  const edits={}; snapEdited.forEach(fn=>{ const fr=frames.find(f=>f.file===fn);
    if(fr) edits[fn]=fr.regions.map(r=>({tid:r.tid,box:r.box,x:r.x})); });
  const snapClasses=[...CLASSES]; const hadClassEdit=classesDirty;
  try{
    const j=await (await fetch('/save',{method:'POST',
      body:JSON.stringify({clip:clip,cls:snapCls,edits:edits,classes:snapClasses})})).json();
    if(hadClassEdit && snapClasses.join('\n')===CLASSES.join('\n')) classesDirty=false;
    // fold the persisted baseline in: anything edited since is still dirty and will autosave again
    for(const t in snapCls) orig[t]=snapCls[t];
    snapEdited.forEach(fn=>edited.delete(fn));
    markRows(); refresh();
    if(announce) toast('Saved · '+(j.regions||0)+' boxes → '+outName);
  }catch(e){ if(announce) toast('Save failed: '+e); }
  finally{
    saving=false;
    if(saveAgain){ saveAgain=false; scheduleAutosave(0); }   // a change arrived mid-save
  }
}
function save(announce){ return doSave(!!announce); }        // Save button (announce=true)
function scheduleAutosave(delay){                            // debounced auto-save after edits
  if(!outName) return;                                       // nothing open yet
  if(autosaveTimer) clearTimeout(autosaveTimer);
  autosaveTimer=setTimeout(()=>{ autosaveTimer=null; if(dirtyCount()) doSave(false); },
                           delay==null?900:delay);
}
function openHelp(){ document.getElementById('helpdlg').style.display='flex'; }
function closeHelp(){ document.getElementById('helpdlg').style.display='none'; }
function toggleTheme(){ const r=document.documentElement;
  const next=(r.dataset.theme||'dark')==='light'?'dark':'light';          // dark is the CSS default
  r.dataset.theme=next; try{ localStorage.setItem('relabel-theme',next); }catch(e){} }
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.opacity=1;setTimeout(()=>t.style.opacity=0,2500);}

// build the merge-into options only when the user actually opens the dropdown (fires before it renders)
document.getElementById('idsel').addEventListener('mousedown',()=>{ if(idselStale) buildIdOpts(); });
document.getElementById('idsel').addEventListener('focus',()=>{ if(idselStale) buildIdOpts(); });
// ONE delegated click for the whole object list (was a per-row closure x7700)
document.getElementById('list').addEventListener('click',e=>{
  if(e.target.tagName==='SELECT'||e.target.closest('select')) return;   // let the class dropdown work
  if(e.target.classList.contains('vcls')){ e.stopPropagation(); editClass(e.target); return; }
  const row=e.target.closest('.vrow'); if(row) pick(row.dataset.tid);
});

// init LAST — after every top-level `let` is initialized, so openLoader() can safely read loaderMode
if(clip) load(); else openLoader();   // no project preloaded -> show the Open dialog
