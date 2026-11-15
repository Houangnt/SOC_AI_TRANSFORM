"""Exercise the LifeMate page's SSE lifecycle without a browser dependency."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_lifemate_page_uses_official_endpoint_and_preserves_stream_results():
    repo = Path(__file__).resolve().parents[2]
    script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const elements = new Map();
function element(id){
  if(!elements.has(id)) elements.set(id,{innerHTML:'',disabled:false,scrollIntoView(){}});
  return elements.get(id);
}
const main = {scrollTop:0}, requests = [];
const encoder = new TextEncoder();
const done = {kind:'done',skills:['contacts'],tools:[
  {tool:'contacts.search',args:{query:'Test'},output:'{"ok":true}'}],
  reply:'Đã đọc kết quả',submission:{id:'synthetic',tool_calls:[
    {name:'contacts.search',arguments:{query:'Test'}}],state_hash:'ENV_HASH'}};
const frames = [{kind:'business_skills',skills:['contacts'],rules:[]},
  {kind:'tool',tool:'contacts.search',args:{query:'Test'},output:'{"ok":true}'},done];
const wire=encoder.encode(frames.map(e=>'data: '+JSON.stringify(e)+'\n\n').join(''));
const context=vm.createContext({console,VIEWS:{},TextDecoder,Blob,URL,setTimeout,setInterval,clearInterval,
  location:{hash:'#lifemate'},
  crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},
  document:{getElementById:element,querySelector:()=>main,querySelectorAll:()=>[]},
  fetch:async(url,options)=>{
    requests.push({url,body:JSON.parse(options.body)});
    let offset=0;
    return {ok:true,body:{getReader:()=>({read:async()=>{
      if(offset>=wire.length) return {done:true};
      const value=wire.slice(offset,offset+13); offset+=13; return {done:false,value};
    }})}};
  }});
vm.runInContext(fs.readFileSync('SOC_AI_TRANSFORM/ops/static/js/util.js','utf8'),context);
vm.runInContext(fs.readFileSync('SOC_AI_TRANSFORM/ops/static/js/lifemate.js','utf8'),context);
vm.runInContext(fs.readFileSync('SOC_AI_TRANSFORM/ops/static/js/render.js','utf8'),context);
vm.runInContext(`LM.meta={available:true,splits:['public_test'],provider:'fake',rules:6,
  skills:[{id:'contacts',title:'Danh bạ',description:'Sửa số điện thoại'}]};
  LM.sample={context:{installed_apps:{}},history:[],transcript_error:''};
  LM.sampleId='synthetic'; LM.text='</textarea><img src=x onerror=alert(1)>';
  LM.samples=[{id:'synthetic'}];`,context);
const html=vm.runInContext('lifeMateView()',context);
assert.ok(!html.includes('<img src=x'));
assert.ok(html.includes('&lt;/textarea&gt;'));
assert.equal(vm.runInContext('lifeMateCanRun()',context),true);
(async()=>{
  await vm.runInContext('lifeMateRun()',context);
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,'/api/lifemate/run');
  assert.equal(vm.runInContext('LM.busy',context),false);
  assert.equal(vm.runInContext('LM.result.submission.state_hash',context),'ENV_HASH');
  assert.equal(vm.runInContext('LM.tools.length',context),1);
  assert.ok(element('view').innerHTML.includes('ENV_HASH'));
  assert.ok(element('view').innerHTML.includes('Đã đọc kết quả'));
  vm.runInContext(`LM.catalog={enabled_count:1,tools:[
    {name:'contacts.search',enabled:true,parameters:{type:'object'}},
    {name:'banking.transfer',enabled:false,parameters:{type:'object'}}]};
    lifeMateSetTab('tools');`,context);
  assert.equal(context.location.hash,'#lifemate/tools');
  let tools=vm.runInContext('lifeMateCatalogCards()',context);
  assert.ok(tools.includes('contacts.search'));
  assert.ok(!tools.includes('banking.transfer'));
  vm.runInContext('LM.onlyEnabled=false',context);
  tools=vm.runInContext('lifeMateCatalogCards()',context);
  assert.ok(tools.includes('banking.transfer'));
  assert.ok(!tools.includes('save_note'));
  vm.runInContext('LM.ready=Promise.resolve(); LM.tab="run"',context);
  await vm.runInContext('sendChat({value:"Bạn có tool gì?",focus(){}})',context);
  assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/api/chat/stream');
  assert.deepEqual(requests[1].body.lifemate,{split:'public_test',sample_id:'synthetic'});
  assert.equal(vm.runInContext('CHAT[CHAT.length-1].submission.state_hash',context),'ENV_HASH');
  vm.runInContext("LM.sample.transcript_error='missing history'",context);
  assert.equal(vm.runInContext('lifeMateCanRun()',context),false);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([shutil.which("node"), "-e", script], cwd=repo,
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
