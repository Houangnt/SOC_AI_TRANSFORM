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
  archSVG:()=>'',gateSplit:()=>'',graphPanel:()=>'',
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
vm.runInContext(fs.readFileSync('SOC_AI_TRANSFORM/ops/static/js/views.js','utf8'),context);
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
  vm.runInContext('LM.sample.text="<img src=x onerror=alert(1)>";lifeMateSyncChatScope()',context);
  const overview=vm.runInContext(`VIEWS.overview({stats:{turns:2,tool_calls:5},
    facts:[],episodes:[],turns:[]})`,context);
  assert.ok(overview.includes('id="overview-available-tools">1</b>'));
  assert.ok(overview.includes('Lượt gọi đã ghi</span><b>5</b>'));
  assert.ok(!overview.includes('<img src=x'));
  assert.ok(overview.includes('&lt;img src=x'));
  assert.equal(element('overview-available-tools').textContent,1);
  const quota=vm.runInContext(`renderAssistantReply('RateLimitError: 429 quota exceeded <script>')`,context);
  assert.ok(quota.includes('Đã đạt giới hạn API'));
  assert.ok(quota.includes('&lt;script&gt;'));
  assert.ok(!quota.includes('<script>'));
  assert.equal(vm.runInContext('renderAssistantReply("Xin chào")',context),'<div class="mdp">Xin chào</div>');
  vm.runInContext('LM.ready=Promise.resolve(); LM.tab="run"',context);
  await vm.runInContext('sendChat({value:"Bạn có tool gì?",focus(){}})',context);
  assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/api/chat/stream');
  assert.deepEqual(requests[1].body.lifemate,{split:'public_test',sample_id:'synthetic'});
  assert.equal(vm.runInContext('CHAT[CHAT.length-1].submission.state_hash',context),'ENV_HASH');
  vm.runInContext("LM.sample.transcript_error='missing history'",context);
  assert.equal(vm.runInContext('lifeMateCanRun()',context),false);
  // ASR is an explicit, separate step. Its history travels with the agent request.
  context.fetch=async(url,options)=>{
    requests.push({url,body:JSON.parse(options.body)});
    assert.equal(vm.runInContext('lifeMateCanRun()',context),false);
    return {ok:true,json:async()=>({text:'recognized current',mode:'live',
      transcripts:{synthetic:'recognized current',synthetic_u1:'recognized history'},
      history:[{role:'user',text:'recognized history'}],
      clips:[{audio:'synthetic',text:'recognized current'}]})};
  };
  vm.runInContext(`LM.meta.asr={name:'PhoWhisper',adapter_available:true,
    saved_predictions:155,max_seconds:120}; LM.sample.audio_available=true`,context);
  assert.ok(vm.runInContext('lifeMateASR()',context).includes('Chạy ASR từ audio'));
  await vm.runInContext("lifeMateRecognize('live')",context);
  assert.equal(requests.length,3); // ASR did not automatically execute the agent.
  assert.equal(requests[2].url,'/api/lifemate/asr');
  assert.equal(vm.runInContext('LM.text',context),'recognized current');
  assert.equal(vm.runInContext('LM.sample.history[0].text',context),'recognized history');
  assert.equal(vm.runInContext('lifeMateCanRun()',context),true);
  context.fetch=async(url,options)=>{
    const payload=JSON.parse(options.body);
    assert.equal(url,'/api/lifemate/run');
    assert.equal(payload.asr_transcripts.synthetic_u1,'recognized history');
    assert.equal(payload.text,'corrected current');
    let sent=false;
    return {ok:true,body:{getReader:()=>({read:async()=>{
      if(sent) return {done:true}; sent=true;
      return {done:false,value:wire};
    }})}};
  };
  vm.runInContext("lifeMateEditText('corrected current')",context);
  await vm.runInContext('lifeMateRun()',context);
  // Failed ASR must retain the last good transcript and unlock controls.
  context.fetch=async()=>({ok:true,json:async()=>({error:'Missing checkpoint'})});
  await vm.runInContext("lifeMateRecognize('live')",context);
  assert.equal(vm.runInContext('LM.text',context),'corrected current');
  assert.equal(vm.runInContext('LM.asrBusy',context),false);
  assert.equal(vm.runInContext('LM.error',context),'Missing checkpoint');
  vm.runInContext("lifeMateAudioFile({name:'new.wav',size:128})",context);
  assert.equal(vm.runInContext('lifeMateCanRun()',context),false);
  assert.equal(vm.runInContext('LM.audioPending',context),true);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([shutil.which("node"), "-e", script], cwd=repo,
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
