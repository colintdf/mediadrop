'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const functions = source.slice(source.indexOf('function inferFilename('), source.indexOf('const fields='));
const elements = {};
const $ = id => elements[id] ||= {value:'mp3'};
const sent = [];
class Upload {
  constructor() { this.upload = {}; this.headers = {}; }
  open(method, url) { this.url = url; }
  setRequestHeader(key, value) { this.headers[key] = value; }
  send(file) {
    sent.push({url:this.url, headers:this.headers, file});
    this.status=202; this.responseText=JSON.stringify({job:'job-'+sent.length});
    this.onload();
  }
}
const files = [
  {name:'Emily Burns - Seven Scenes From The Same Summer - 01 Test Drive.mp3',size:100},
  {name:'The Anchoress - The Art Of Losing - 02 Let It Hurt.mp3',size:200}
];
const context = vm.createContext({
  $, selected:'music', state:{folders:[{id:'music',name:'Music',available:true}],conversion:true},
  pending:[],sending:false,supported:/\.mp3$/i,
  crypto:{randomUUID:()=>String(Math.random())},XMLHttpRequest:Upload,
  renderTransfers(){},banner(){},refresh(){},window:{addEventListener(){}}
});
vm.runInContext(functions, context);
context.files=files;
vm.runInContext('addFiles(files)',context);
assert.equal(context.pending.length,2);
assert.equal(context.pending[0].inferred.artist,'Emily Burns');
assert.equal(context.pending[1].inferred.artist,'The Anchoress');
assert.equal(context.pending[0].inferred.album,'Seven Scenes From The Same Summer');
assert.equal(context.pending[1].inferred.album,'The Art Of Losing');
assert.ok(context.pending.every(item=>item.layout==='auto'));
vm.runInContext("pending.forEach(item=>item.status='waiting')",context);
(async()=>{
  await vm.runInContext('pump()',context);
  assert.equal(sent.length,2);
  for(let i=0;i<2;i++){
    const url=new URL(sent[i].url,'http://localhost');
    assert.equal(url.searchParams.get('layout'),'auto');
    assert.equal(url.searchParams.get('name'),files[i].name);
    assert.equal(sent[i].file,files[i]);
    assert.deepEqual(JSON.parse(decodeURIComponent(sent[i].headers['X-MediaDrop-Tags'])),{});
  }
  console.log('PASS: default mixed web batch uses auto folders, individual filenames and file bodies, without shared artist overrides');
})().catch(error=>{console.error(error);process.exitCode=1;});
