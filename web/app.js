'use strict';
const $ = id => document.getElementById(id);
let state = {folders: [], jobs: []}, selected = localStorage.getItem('mediadrop-folder'), pending = [], sending = false, connected = false, connectionLost = false;
const supported = /\.(mp3|wav|wave|flac|m4a|aac|ogg|opus|aif|aiff|wma)$/i;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const size = bytes => bytes >= 1e9 ? (bytes/1e9).toFixed(1)+' GB' : bytes >= 1e6 ? (bytes/1e6).toFixed(1)+' MB' : Math.ceil(bytes/1e3)+' KB';
function banner(message) { $('banner').textContent = message; $('banner').hidden = !message; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-MediaDrop':'1'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}
async function refresh(){
  try {
    state = await api('/api/state'); connected=true;
    if(connectionLost){banner('');connectionLost=false;}
    if(!state.folders.some(f=>f.id===selected && f.available)) selected=state.folders.find(f=>f.available)?.id || null;
    renderFolders(); renderTransfers(); refreshLibrary(); updateArtworkStatus();
    if(!state.conversion) banner('FFmpeg is missing on the server. Follow the setup instructions, then restart MediaDrop.');
  } catch(error) { connected=false;connectionLost=true;banner('Connection lost. Check that MediaDrop is running on the server.'); }
}
function renderFolders(){
  const folders=state.folders.filter(f=>f.type==='music');
  $('destinations').innerHTML=folders.map(f=>`<button class="destination ${f.id===selected?'selected':''}" data-folder="${escapeHTML(f.id)}" aria-pressed="${f.id===selected}" ${!f.available?'disabled':''}><span class="folder-icon" aria-hidden="true">▱</span><span><strong>${escapeHTML(f.name)}</strong><small>${f.available?escapeHTML(f.path):'Drive or folder unavailable'}</small></span><span class="radio" aria-hidden="true"></span></button>`).join('')+'<button class="destination add" id="addFolder">+ Add a folder</button>';
  $('destinations').querySelectorAll('[data-folder]').forEach(button=>button.onclick=()=>{ selected=button.dataset.folder; localStorage.setItem('mediadrop-folder',selected); renderFolders(); });
  $('addFolder').onclick=openFolders;
  const options='<option value="">All music folders</option>'+folders.map(f=>`<option value="${escapeHTML(f.id)}">${escapeHTML(f.name)}</option>`).join('');
  if($('libraryFolder').innerHTML!==options){const old=$('libraryFolder').value;$('libraryFolder').innerHTML=options;$('libraryFolder').value=old;}
  $('dropzone').disabled=!selected || !state.conversion;
  $('folderList').innerHTML=folders.map(f=>`<div class="folder-row"><div><strong>${escapeHTML(f.name)}</strong><small>${escapeHTML(f.path)}${f.available?'':' · Unavailable'}</small></div><button class="remove" data-remove="${escapeHTML(f.id)}" aria-label="Remove ${escapeHTML(f.name)} destination">Remove</button></div>`).join('');
  $('folderList').querySelectorAll('[data-remove]').forEach(button=>button.onclick=async()=>{
    try { await api('/api/folders/remove',{id:button.dataset.remove}); await refresh(); }
    catch(e){ $('folderError').textContent=e.message; }
  });
}
function renderTransfers(){
  // As soon as a server job is seen, it replaces its browser upload row.
  const ids=new Set(state.jobs.map(j=>j.id)); pending=pending.filter(p=>!p.job || !ids.has(p.job));
  const rows=[...pending.slice().reverse(),...state.jobs.slice().reverse()];
  const active=rows.filter(j=>!['done','failed','draft'].includes(j.status)).length;
  $('uploadStaged').hidden=!pending.some(j=>j.status==='draft');
  $('uploadStaged').textContent=`Upload staged tracks (${pending.filter(j=>j.status==='draft').length})`;
  $('queueCount').textContent=rows.length; $('queueSummary').textContent=active?`${active} IN PROGRESS`:'ALL CAUGHT UP';
  if(!rows.length){ $('transfers').innerHTML='<div class="empty">Your next favourite belongs here.<small>Uploads and conversions will appear as you add music.</small></div>'; return; }
  $('transfers').innerHTML=rows.map(j=>{
    const statuses={draft:'Ready to upload',waiting:'Waiting to upload',uploading:`Uploading ${j.progress||0}%`,queued:'Waiting to convert',checking:'Checking audio',converting:`Converting ${j.progress||0}%`,done:'Ready to play',failed:'Needs attention'};
    const detail=j.status==='failed'?j.error:`${size(j.bytes)} · ${j.folder}${j.status==='done'?` · ${j.converted?'Converted to MP3':'Original MP3'} · ${j.output}`:''}`;
    return `<div class="transfer ${j.status==='failed'?'failed':''}"><span class="track-icon" aria-hidden="true">${j.status==='done'?'✓':'♫'}</span><div class="track-main"><strong>${escapeHTML(j.name)}</strong><small>${escapeHTML(detail)}</small>${!['done','failed','waiting','draft'].includes(j.status)?`<div class="progress ${['queued','checking'].includes(j.status)?'indeterminate':''}"><i></i></div>`:''}</div><div class="track-buttons"><div class="track-status">${escapeHTML(statuses[j.status]||j.status)}</div>${j.status==='draft'||j.status==='done'?`<button class="edit-track" data-edit-track="${escapeHTML(j.id||j.uid)}" data-draft="${j.status==='draft'}">Edit details</button>`:''}${j.status==='draft'?`<button class="remove-draft" data-remove-draft="${escapeHTML(j.uid)}">Remove</button>`:''}</div></div>`;
  }).join('');
  $('transfers').querySelectorAll('[data-edit-track]').forEach(button=>button.onclick=()=>openMetadata(button.dataset.editTrack,button.dataset.draft==='true'));
  $('transfers').querySelectorAll('[data-remove-draft]').forEach(button=>button.onclick=()=>{pending=pending.filter(j=>j.uid!==button.dataset.removeDraft);renderTransfers();});
  $('transfers').querySelectorAll('.transfer').forEach((row,index)=>{const bar=row.querySelector('.progress i');if(bar && !bar.parentElement.classList.contains('indeterminate'))bar.style.width=(Number(rows[index].progress)||0)+'%';});
}
function openFolders(){ $('folderError').textContent=''; if(!$('folderDialog').open) $('folderDialog').showModal(); }
$('foldersButton').onclick=openFolders; $('closeDialog').onclick=()=>$('folderDialog').close();
$('musicNav').onclick=()=>window.scrollTo({top:0,behavior:'smooth'});
$('folderForm').onsubmit=async e=>{e.preventDefault(); const button=e.target.querySelector('button'); button.disabled=true; $('folderError').textContent=''; try{await api('/api/folders',{name:$('folderName').value,path:$('folderPath').value}); e.target.reset(); await refresh();}catch(error){$('folderError').textContent=error.message;}finally{button.disabled=false;}};
$('dropzone').onclick=()=>$('fileInput').click();
$('fileInput').onchange=e=>{addFiles(Array.from(e.target.files));e.target.value='';};
let dragDepth=0;
$('dropzone').addEventListener('dragenter',e=>{e.preventDefault();dragDepth++;$('dropzone').classList.add('drag');});
$('dropzone').addEventListener('dragover',e=>e.preventDefault());
$('dropzone').addEventListener('dragleave',e=>{e.preventDefault();if(--dragDepth<=0){dragDepth=0;$('dropzone').classList.remove('drag');}});
$('dropzone').addEventListener('drop',e=>{e.preventDefault();dragDepth=0;$('dropzone').classList.remove('drag');addFiles(Array.from(e.dataTransfer.files));});
// Prevent a drop outside the target from navigating away from an upload.
window.addEventListener('dragover',e=>e.preventDefault());window.addEventListener('drop',e=>e.preventDefault());
function addFiles(files){
  const folder=state.folders.find(f=>f.id===selected && f.available);
  if(!folder || !state.conversion){banner('Add and choose an available music folder before uploading.');return;}
  const rejected=[];
  for(const file of files){
    if(!supported.test(file.name) || !file.size || file.size>10*1024**3){rejected.push(file.name);continue;}
    pending.push({uid:crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random(),file,name:file.name,bytes:file.size,folder:folder.name,folderId:folder.id,status:'draft',progress:0,metadata:{},layout:'flat'});
  }
  banner(rejected.length?`Not added: ${rejected.join(', ')}. Choose supported audio files smaller than 10 GB. This version accepts files, not folders.`:'');
  renderTransfers();
}
async function pump(){
  if(sending)return; sending=true;
  try{for(const item of pending.filter(p=>p.status==='waiting')){
    item.status='uploading';renderTransfers();
    try{await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();xhr.open('POST',`/api/upload?folder=${encodeURIComponent(item.folderId)}&name=${encodeURIComponent(item.name)}&layout=${encodeURIComponent(item.layout||'flat')}`);xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.setRequestHeader('X-MediaDrop','1');xhr.setRequestHeader('X-MediaDrop-Tags',encodeURIComponent(JSON.stringify(item.metadata||{})));
      xhr.upload.onprogress=e=>{if(e.lengthComputable){item.progress=Math.round(e.loaded/e.total*100);renderTransfers();}};
      xhr.onload=()=>{try{const response=JSON.parse(xhr.responseText);if(xhr.status<200||xhr.status>=300)throw new Error(response.error||'Upload failed.');item.job=response.job;item.status='queued';item.progress=0;resolve();}catch(e){reject(e);}};
      xhr.onerror=()=>reject(new Error('Connection interrupted. Please add the file again.'));xhr.onabort=()=>reject(new Error('Upload cancelled.'));xhr.send(item.file);
    });}catch(e){item.status='failed';item.error=e.message;}finally{delete item.file;renderTransfers();}
  }}finally{sending=false;}
  if(pending.some(p=>p.status==='waiting'))pump();
  refresh();
}
window.addEventListener('beforeunload',e=>{if(sending || pending.some(p=>['waiting','draft'].includes(p.status))){e.preventDefault();e.returnValue='';}});


const fields=[['title','Title'],['artist','Track artists (separate with ;)'],['album','Album / release'],['album_artist','Album artist'],['track','Track number'],['disc','Disc number'],['date','Year / date'],['genre','Genre']];
let editing=null,libraryPage=0,libraryTotal=0,libraryTracks=[],libraryRequest=0,libraryView='artists',libraryArtist=null,libraryRelease=null,libraryPageSize=24;
$('metadataFields').innerHTML=fields.map(([key,label])=>`<div><label for="tag-${key}">${label}</label><input id="tag-${key}" name="${key}" maxlength="300" placeholder="${['track','disc'].includes(key)?'e.g. 1 or 1/12':key==='date'?'e.g. 2026':''}"></div>`).join('');
$('metadataFields').querySelectorAll('input').forEach(input=>input.oninput=()=>{if(editing)editing.changed.add(input.name);previewPath();});
$('trackLayout').onchange=previewPath;$('trackFolder').onchange=previewPath;
$('closeMetadata').onclick=()=>{if(!$('saveMetadata').disabled){$('metadataDialog').close();editing=null;}};
$('metadataDialog').addEventListener('cancel',e=>{if($('saveMetadata').disabled)e.preventDefault();else editing=null;});
function editorValues(){return Object.fromEntries(fields.map(([k])=>[k,$('tag-'+k).value.trim()]));}
function pathPart(text){return text.replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').replace(/^[ .]+|[ .]+$/g,'');}
function artistNames(value){
  const names=[],seen=new Set();
  for(const part of String(value||'').split(';')){const name=part.trim(),key=name.toLowerCase();if(name&&!seen.has(key)){names.push(name);seen.add(key);}}
  return names;
}
function primaryArtist(tags){return artistNames(tags.album_artist)[0]||artistNames(tags.artist)[0]||'';}
function displayCredits(value){return artistNames(value).join(' · ');}
function trackCredits(track){
  if(track.credits?.length)return track.credits.map(artist=>`<button type="button" class="credit-link" data-credit-name="${escapeHTML(artist.name)}" data-credit-key="${escapeHTML(artist.key)}">${escapeHTML(artist.name)}</button>`).join('<span class="credit-separator"> · </span>');
  return escapeHTML(displayCredits(track.metadata.artist)||libraryArtist?.name||'Unknown artist');
}
function previewPath(){
  if(!editing)return;
  const tags=editorValues(),layout=$('trackLayout').value,folder=state.folders.find(f=>f.id===$('trackFolder').value);
  if(layout==='keep'){$('trackPath').textContent=editing.path||'';return;}
  let parts=[folder?.path||'Choose a music folder'];
  if(layout==='single'||layout==='album')parts.push(pathPart(primaryArtist(tags))||'[Artist]');
  if(layout==='album')parts.push(pathPart(tags.album)||'[Album]');
  parts.push(editing.draft?editing.name.replace(/\.[^.]+$/,'.mp3'):editing.path.split('/').pop());
  $('trackPath').textContent=parts.join('/');
}
async function openMetadata(id,draft=false){
  if($('metadataDialog').open)return;
  $('metadataError').textContent='';$('sharedFields').checked=false;
  try{
    let metadata,track,path='',rev;
    if(draft){track=pending.find(j=>j.uid===id&&j.status==='draft');if(!track)return;metadata=track.metadata||{};}
    else{const result=await api('/api/metadata/read',{id});metadata=result.metadata;path=result.path;rev=result.revision;track=state.jobs.find(j=>j.id===id)||libraryTracks.find(j=>j.id===id)||{name:path.split('/').pop()};}
    editing={id,draft,name:track.name,path,revision:rev,changed:new Set(),track};
    $('metadataTrack').textContent=track.name;
    fields.forEach(([key])=>{$('tag-'+key).value=metadata[key]||'';});
    $('trackFolder').innerHTML=state.folders.filter(f=>f.type==='music').map(f=>`<option value="${escapeHTML(f.id)}">${escapeHTML(f.name)}</option>`).join('');
    $('trackFolder').value=track.folderId||track.folder_id||selected||'';
    $('trackLayout').querySelector('[value="keep"]').disabled=draft;
    $('trackLayout').value=draft?(track.layout||'flat'):'keep';
    $('sharedFieldsLabel').hidden=!draft;
    $('metadataHint').textContent=draft?'Separate track performers with semicolons; Album artist keeps a release together. Only fields you change replace existing tags. Leave other fields untouched to preserve them. Singles sit in the artist folder; albums get their own folder.':'Current tags are read from the audio file. Clearing a field removes that tag. Choose a destination to move the track without re-encoding.';
    $('saveMetadata').textContent=draft?'Save details before upload':'Save tags and location';
    previewPath();$('metadataDialog').showModal();
  }catch(e){banner(e.message);}
}
$('metadataForm').onsubmit=async e=>{
  e.preventDefault();if(!editing)return;
  const button=$('saveMetadata');button.disabled=true;$('metadataError').textContent='';
  try{
    const values=editorValues(),layout=$('trackLayout').value,folder=$('trackFolder').value;
    if(['single','album'].includes(layout)&&!primaryArtist(values))throw new Error('Enter an artist or album artist for the folder name.');
    if(layout==='album'&&!values.album)throw new Error('Enter the album name for its folder.');
    const changes=Object.fromEntries([...editing.changed].map(k=>[k,values[k]]));
    if(editing.draft){
      const item=editing.track;item.metadata={...item.metadata,...changes};item.layout=layout;item.folderId=folder;item.folder=state.folders.find(f=>f.id===folder)?.name||item.folder;
      if($('sharedFields').checked){
        const shared=Object.fromEntries(Object.entries(changes).filter(([k])=>['artist','album_artist','date','genre'].includes(k)));
        for(const draft of pending.filter(j=>j.status==='draft'&&j!==item))draft.metadata={...draft.metadata,...shared};
      }
      renderTransfers();
    }else{
      await api('/api/metadata/save',{id:editing.id,revision:editing.revision,metadata:changes,layout,folder});
      await refresh();banner('Track details saved.');
    }
    $('metadataDialog').close();editing=null;
  }catch(error){$('metadataError').textContent=error.message;}finally{button.disabled=false;}
};
$('uploadStaged').onclick=()=>{for(const item of pending.filter(p=>p.status==='draft'))item.status='waiting';renderTransfers();pump();};
function libraryNavigate(view,artist=null,release=null){
  selectedReleaseKeys.clear();selectedTrackIds.clear();
  libraryView=view;libraryArtist=artist;libraryRelease=release;libraryPage=0;refreshLibrary();
}
function libraryCrumbs(){
  $('libraryBreadcrumbs').innerHTML=`<button data-library-home ${libraryView==='artists'?'aria-current="page"':''}>All artists</button>${libraryArtist?`<span>/</span><button data-library-artist ${libraryView==='releases'?'aria-current="page"':''}>${escapeHTML(libraryArtist.name)}</button>`:''}${libraryRelease?`<span>/</span><span aria-current="page">${escapeHTML(libraryRelease.name)}</span>`:''}`;
  $('libraryBreadcrumbs').querySelector('[data-library-home]').onclick=()=>libraryNavigate('artists');
  const artistButton=$('libraryBreadcrumbs').querySelector('[data-library-artist]');
  if(artistButton)artistButton.onclick=()=>libraryNavigate('releases',libraryArtist);
}
function tileInitials(name){return name.trim().split(/\s+/).slice(0,2).map(p=>p[0]||'').join('').toUpperCase();}
function tileColour(name){let value=0;for(const c of name)value=(value*31+c.charCodeAt(0))>>>0;return value%6;}
async function refreshLibrary(){
  if(!connected)return;const request=++libraryRequest;
  try{
    const result=await api('/api/library?'+new URLSearchParams({q:$('librarySearch').value,folder:$('libraryFolder').value,page:String(libraryPage),view:libraryView,artist:libraryArtist?.key||'',release:libraryRelease?.key||''}));
    if(request!==libraryRequest)return;
    libraryRows=result.items;libraryTracks=libraryView==='tracks'?result.items:[];libraryTotal=result.total;libraryPageSize=result.page_size;
    $('libraryCount').textContent=result.track_total;
    $('scanLibrary').disabled=result.scan.running;
    $('scanStatus').textContent=result.scan.running?`Scanning music folders: ${result.scan.scanned} files checked…`:`${result.track_total} tracks indexed${result.scan.errors?` · ${result.scan.errors} files or folders could not be read`:''}. Scan folders to pick up external changes.`;
    libraryCrumbs();
    const container=$('libraryTracks');container.className=libraryView==='tracks'?'transfers':'artist-grid';
    let html;
    if(libraryView==='artists'){
      html=result.items.map((artist,index)=>`<button class="library-tile artist-tile" data-tile="${index}"><span class="tile-art tile-colour-${tileColour(artist.name)}">${tilePhoto(artist.image)}<span class="artist-monogram" aria-hidden="true">${escapeHTML(tileInitials(artist.name))}</span><span class="tile-open" aria-hidden="true">↗</span></span><strong>${escapeHTML(artist.name)}</strong><small>${artist.release_count} ${artist.release_count===1?'release':'releases'} · ${artist.track_count} ${artist.track_count===1?'track':'tracks'}</small></button>`).join('');
    }else if(libraryView==='releases'){
      html=result.items.map((release,index)=>`<article class="release-card"><label class="tile-select"><input type="checkbox" data-select-release="${index}" ${selectedReleaseKeys.has(release.key)?'checked':''} aria-label="Select ${escapeHTML(release.name)}"><span>Select release</span></label><button class="library-tile release-tile" data-tile="${index}"><span class="tile-art tile-colour-${tileColour(release.name)}">${tilePhoto(release.image)}<span class="release-record" aria-hidden="true"><i></i></span><span class="release-type">${release.appears_on?'APPEARS ON':release.kind==='album'?'ALBUM':'SINGLE'}</span><span class="tile-open" aria-hidden="true">↗</span></span><strong>${escapeHTML(release.name)}</strong><small>${escapeHTML(release.appears_on?release.artist+' · ':'')}${escapeHTML(release.year?release.year+' · ':'')}${release.track_count} ${release.track_count===1?'track':'tracks'}</small></button></article>`).join('');
    }else{
      html=result.items.map(t=>`<div class="transfer"><input class="track-select" type="checkbox" data-select-track="${escapeHTML(t.id)}" ${selectedTrackIds.has(t.id)?'checked':''} aria-label="Select ${escapeHTML(t.metadata.title||t.name)}"><span class="track-icon track-number">${escapeHTML(t.metadata.track?.split('/')[0]||'♫')}</span><div class="track-main"><strong>${escapeHTML(t.metadata.title||t.name)}</strong><small>${trackCredits(t)}</small><small>${escapeHTML(t.folder+' / '+t.relative)}</small></div><div class="track-buttons"><button class="edit-track" data-library-edit="${escapeHTML(t.id)}">Edit details</button></div></div>`).join('');
    }
    // Polling leaves focused tiles intact while the current view is unchanged.
    const markup=html||'<div class="empty library-empty">Nothing here yet.<small>Scan your music folders or try another search.</small></div>';
    if(container.innerHTML!==markup)container.innerHTML=markup;
    container.querySelectorAll('[data-tile]').forEach(button=>button.onclick=()=>{
      const item=result.items[Number(button.dataset.tile)];
      if(libraryView==='artists')libraryNavigate('releases',item);
      else libraryNavigate('tracks',libraryArtist,item);
    });
    container.querySelectorAll('[data-select-release]').forEach(input=>input.onchange=()=>{const item=result.items[Number(input.dataset.selectRelease)];if(input.checked)selectedReleaseKeys.set(item.key,item.track_count);else selectedReleaseKeys.delete(item.key);updateBulkToolbar();});
    container.querySelectorAll('[data-select-track]').forEach(input=>input.onchange=()=>{if(input.checked)selectedTrackIds.add(input.dataset.selectTrack);else selectedTrackIds.delete(input.dataset.selectTrack);updateBulkToolbar();});
    container.querySelectorAll('.tile-photo').forEach(img=>img.onerror=()=>{failedImages.add(img.getAttribute('src'));img.remove();});
    updateBulkToolbar();
    container.querySelectorAll('[data-credit-key]').forEach(button=>button.onclick=()=>libraryNavigate('releases',{key:button.dataset.creditKey,name:button.dataset.creditName}));
    container.querySelectorAll('[data-library-edit]').forEach(button=>button.onclick=()=>openMetadata(button.dataset.libraryEdit));
    $('libraryPrevious').disabled=libraryPage===0;$('libraryNext').disabled=(libraryPage+1)*libraryPageSize>=result.total;
    $('libraryPage').textContent=result.total?`PAGE ${libraryPage+1} OF ${Math.ceil(result.total/libraryPageSize)}`:'NO RESULTS';
  }catch(e){if(connected)$('scanStatus').textContent=e.message;}
}
let searchTimer;$('librarySearch').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>libraryNavigate('artists'),250);};
$('libraryFolder').onchange=()=>libraryNavigate('artists');
$('libraryPrevious').onclick=()=>{if(libraryPage>0){libraryPage--;refreshLibrary();}};
$('libraryNext').onclick=()=>{if((libraryPage+1)*libraryPageSize<libraryTotal){libraryPage++;refreshLibrary();}};
$('scanLibrary').onclick=async()=>{try{await api('/api/library/scan',{});refreshLibrary();}catch(e){banner(e.message);}};


let libraryRows=[],selectedReleaseKeys=new Map(),selectedTrackIds=new Set(),bulkPlan=null,bulkRunning=false;
const failedImages=new Set();
function tilePhoto(url){return url&&!failedImages.has(url)?`<img class="tile-photo" src="${escapeHTML(url)}" alt="" loading="lazy">`:'';}
function updateBulkToolbar(){
  $('bulkToolbar').hidden=libraryView==='artists';
  $('editArtistTracks').hidden=libraryView!=='releases';
  const count=libraryView==='releases'?[...selectedReleaseKeys.values()].reduce((a,b)=>a+b,0):selectedTrackIds.size;
  $('bulkSelectionSummary').textContent=count?`${count} tracks selected`:'Select tracks or releases to edit shared tags';
  $('editSelectedTracks').disabled=count===0;
}
$('selectLibraryPage').onclick=()=>{
  if(libraryView==='releases')for(const item of libraryRows)selectedReleaseKeys.set(item.key,item.track_count);
  else for(const item of libraryRows)selectedTrackIds.add(item.id);
  refreshLibrary();
};
$('clearLibrarySelection').onclick=()=>{selectedReleaseKeys.clear();selectedTrackIds.clear();refreshLibrary();};
$('editSelectedTracks').onclick=()=>{
  const scope=libraryView==='tracks'?{ids:[...selectedTrackIds]}:{artist:libraryArtist.key,releases:[...selectedReleaseKeys.keys()],folder:$('libraryFolder').value,q:$('librarySearch').value};
  openBulk(scope);
};
$('editArtistTracks').onclick=()=>openBulk({artist:libraryArtist.key,folder:$('libraryFolder').value,q:$('librarySearch').value});
async function openBulk(scope){
  $('editSelectedTracks').disabled=true;$('editArtistTracks').disabled=true;banner('Reading selected track details…');
  try{
    bulkPlan=await api('/api/bulk/prepare',scope);bulkRunning=false;
    $('bulkSummary').textContent=`Edit shared details for ${bulkPlan.count} tracks.`;
    const labels={artist:'Track artist credits',album_artist:'Album artist',album:'Album name',genre:'Genre',date:'Year / date'};
    $('bulkFields').innerHTML=Object.keys(labels).map(key=>{
      const allowed=bulkPlan.allowed.includes(key),value=bulkPlan.common[key];
      return `<div class="bulk-field ${allowed?'':'bulk-field-disabled'}"><label class="bulk-field-label"><input type="checkbox" data-bulk-key="${key}" ${allowed?'':'disabled'}> ${labels[key]}</label><input id="bulk-${key}" maxlength="300" value="${escapeHTML(value??'')}" placeholder="${value===null?'Mixed values: unchanged unless checked':'Check the field to change or clear it'}" aria-label="${labels[key]} value" disabled></div>`;
    }).join('');
    $('bulkFields').querySelectorAll('[data-bulk-key]').forEach(input=>input.onchange=()=>{$('bulk-'+input.dataset.bulkKey).disabled=!input.checked;$('saveBulk').disabled=!$('bulkFields').querySelector('input[type=checkbox]:checked');});
    $('bulkAlbumHint').textContent=bulkPlan.allow_album?'All selected tracks belong to the same album, so its name can be changed explicitly. Folder names stay unchanged.':'Album names are protected for singles and mixed releases. Edit those individually to keep each release distinct.';
    $('bulkNames').innerHTML=bulkPlan.names.map(name=>`<li>${escapeHTML(name)}</li>`).join('');
    $('bulkProgress').textContent='';$('bulkResults').textContent='';$('bulkError').textContent='';$('saveBulk').disabled=true;$('saveBulk').hidden=false;
    $('bulkDialog').showModal();banner('');
  }catch(e){banner(e.message);}finally{$('editArtistTracks').disabled=false;updateBulkToolbar();}
}
$('closeBulk').onclick=()=>{if(!bulkRunning)$('bulkDialog').close();};
$('bulkDialog').addEventListener('cancel',e=>{if(bulkRunning)e.preventDefault();});
$('bulkForm').onsubmit=async e=>{
  e.preventDefault();if(!bulkPlan||bulkRunning)return;
  const changes={};$('bulkFields').querySelectorAll('input[type=checkbox]:checked').forEach(input=>{changes[input.dataset.bulkKey]=$('bulk-'+input.dataset.bulkKey).value.trim();});
  if(!Object.keys(changes).length)return;
  $('saveBulk').disabled=true;$('bulkError').textContent='';bulkRunning=true;
  try{
    await api('/api/bulk/save',{id:bulkPlan.id,metadata:changes});
    $('bulkFields').querySelectorAll('input').forEach(input=>input.disabled=true);
    pollBulk();
  }catch(error){$('bulkError').textContent=error.message;bulkRunning=false;$('saveBulk').disabled=false;}
};
async function pollBulk(){
  try{
    const result=await api('/api/bulk/status?id='+encodeURIComponent(bulkPlan.id));
    $('bulkProgress').textContent=`${result.completed} of ${result.total} tracks processed.`;
    if(result.status==='running'){setTimeout(pollBulk,1000);return;}
    bulkRunning=false;$('saveBulk').hidden=true;
    const successful=result.results.filter(r=>r.ok).length,failed=result.results.filter(r=>!r.ok);
    $('bulkProgress').textContent=`${successful} updated, ${failed.length} failed, ${result.total-result.completed} unchanged/unprocessed.`;
    $('bulkError').textContent=result.error||'';
    $('bulkResults').innerHTML=failed.map(r=>`<p>${escapeHTML(r.name)}: ${escapeHTML(r.error)}</p>`).join('');
    selectedReleaseKeys.clear();selectedTrackIds.clear();await refresh();
  }catch(error){bulkRunning=false;$('bulkError').textContent=error.message;$('saveBulk').hidden=true;}
}
function updateArtworkStatus(){
  const artwork=state.artwork||{},status=artwork.status||{};
  $('artworkStatus').textContent=status.running?'Syncing artwork references…':status.error?status.error:artwork.provider==='none'||!artwork.provider?'No artwork source connected.':`${status.matched||0} artist / release artwork matches cached.`;
  $('syncArtwork').disabled=!!status.running||artwork.provider==='none';
  $('saveArtwork').disabled=!!status.running;
}
function artworkFields(){
  const provider=$('artworkProvider').value;
  $('artworkConnectionFields').hidden=provider==='none';$('plexSectionField').hidden=provider!=='plex';
  $('artworkUrl').placeholder=provider==='lidarr'?'http://192.168.1.20:8686':'http://192.168.1.20:32400';
}
$('artworkButton').onclick=()=>{
  const settings=state.artwork||{};
  $('artworkProvider').value=settings.provider||'none';$('artworkUrl').value=settings.url||'';$('artworkSection').value=settings.section||'';$('artworkCredential').value='';
  $('artworkCredential').placeholder=settings.has_credential?'Saved: leave blank to keep it':'Enter the token or API key';
  $('artworkError').textContent='';artworkFields();updateArtworkStatus();$('artworkDialog').showModal();
};
$('artworkProvider').onchange=artworkFields;$('closeArtwork').onclick=()=>$('artworkDialog').close();
$('artworkForm').onsubmit=async e=>{
  e.preventDefault();$('artworkError').textContent='';$('saveArtwork').disabled=true;
  try{
    await api('/api/artwork/settings',{provider:$('artworkProvider').value,url:$('artworkUrl').value,credential:$('artworkCredential').value,section:$('artworkSection').value});
    $('artworkCredential').value='';failedImages.clear();await refresh();
  }catch(error){$('artworkError').textContent=error.message;$('saveArtwork').disabled=false;}
};
$('syncArtwork').onclick=async()=>{try{await api('/api/artwork/sync',{});failedImages.clear();await refresh();}catch(e){$('artworkError').textContent=e.message;}};
refresh();setInterval(refresh,2500);
