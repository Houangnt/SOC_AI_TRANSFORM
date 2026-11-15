"""Browser mic lifecycle and PCM upload, with synthetic microphone samples."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_microphone_records_wav_recognizes_and_releases_devices():
    script = r"""
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const {File}=require('node:buffer');
let stopped=0,closed=0,latestNode,failResume=false,requests=[];
const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
const track={stop(){stopped++;},onended:null};
class AudioContext {
  constructor(){this.sampleRate=8000;}
  async resume(){if(failResume) throw new Error('device busy');}
  async close(){closed++;}
  createMediaStreamSource(){return {connect(){},disconnect(){}};}
  createScriptProcessor(){latestNode={connect(){},disconnect(){},onaudioprocess:null}; return latestNode;}
}
class FileReader {
  readAsDataURL(blob){blob.arrayBuffer().then(bytes=>{
    this.result='data:audio/wav;base64,'+Buffer.from(bytes).toString('base64'); this.onload();
  });}
}
const navigator={mediaDevices:{getUserMedia:async()=>stream}};
const context=vm.createContext({navigator,window:{AudioContext},Blob,File,FileReader,URL,
  setInterval,clearInterval,VIEWS:{},location:{hash:'#lifemate'},
  document:{getElementById:()=>null},
  fetch:async(url,options)=>{
    requests.push({url,payload:JSON.parse(options.body)});
    const raw=Buffer.from(requests.at(-1).payload.audio_base64,'base64');
    assert.equal(raw.toString('ascii',0,4),'RIFF');
    assert.equal(raw.readUInt32LE(24),8000);
    return {ok:true,json:async()=>({text:'giọng nói đã nhận dạng',history:[],
      transcripts:{synthetic:'giọng nói đã nhận dạng'},clips:[],mode:'live'})};
  }});
vm.runInContext(fs.readFileSync('SOC_AI_TRANSFORM/ops/static/js/voice-recorder.js','utf8'),context);
vm.runInContext(fs.readFileSync('SOC_AI_TRANSFORM/ops/static/js/lifemate.js','utf8'),context);
function samples(count){latestNode.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(count).fill(0.5)}});}
(async()=>{
  let limits=0;
  context.onLimit=()=>limits++;
  const recorder=await vm.runInContext('startWavRecorder(1,onLimit)',context);
  samples(10000); samples(1000);
  assert.equal(limits,1); assert.equal(recorder.seconds,1);
  const wav=recorder.stop(), bytes=Buffer.from(await wav.arrayBuffer());
  assert.equal(bytes.length,44+8000*2);
  assert.equal(bytes.readUInt32LE(40),16000);
  assert.equal(bytes.readInt16LE(44),16383);
  assert.equal(recorder.stop(),null);
  assert.equal(stopped,1); assert.equal(closed,1);
  failResume=true;
  await assert.rejects(vm.runInContext('startWavRecorder(1,onLimit)',context),/device busy/);
  assert.equal(stopped,2); failResume=false;

  vm.runInContext(`LM.meta={asr:{max_seconds:120}}; LM.sample={history:[],transcript_error:''};
    LM.sampleId='synthetic'; LM.text='previous text';`,context);
  await vm.runInContext('lifeMateStartMic()',context);
  assert.equal(vm.runInContext('lifeMateMicActive()',context),true);
  assert.equal(vm.runInContext('lifeMateCanRun()',context),false);
  await vm.runInContext("lifeMateSelectSample('other')",context);
  assert.equal(vm.runInContext('LM.sampleId',context),'synthetic');
  samples(8000);
  await vm.runInContext('lifeMateFinishMic()',context);
  assert.equal(stopped,3);
  assert.equal(requests.length,1); assert.equal(requests[0].url,'/api/lifemate/asr');
  assert.equal(vm.runInContext('LM.text',context),'giọng nói đã nhận dạng');
  assert.equal(vm.runInContext('lifeMateCanRun()',context),true);
  assert.equal(vm.runInContext('LM.audioFile.type',context),'audio/wav');
  assert.equal(vm.runInContext('LM.asrBusy',context),false);
  assert.equal(vm.runInContext('lifeMateMicActive()',context),false);

  // Cancel never uploads; late permission results must close the device too.
  await vm.runInContext('lifeMateStartMic()',context);
  samples(8000);
  vm.runInContext('lifeMateCancelMic()',context);
  assert.equal(requests.length,1); assert.equal(stopped,4);
  let allow;
  navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{allow=resolve;});
  const pending=vm.runInContext('lifeMateStartMic()',context);
  vm.runInContext('lifeMateCancelMic()',context); allow(stream); await pending;
  assert.equal(stopped,5); assert.equal(vm.runInContext('lifeMateMicActive()',context),false);
  navigator.mediaDevices.getUserMedia=async()=>{const e=new Error('denied');e.name='NotAllowedError';throw e;};
  await vm.runInContext('lifeMateStartMic()',context);
  assert.ok(vm.runInContext('LM.error',context).includes('Micro bị chặn'));
  assert.equal(vm.runInContext('lifeMateMicActive()',context),false);
  assert.equal(requests.length,1);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([shutil.which("node"), "-e", script],
                            cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, encoding="utf-8", timeout=20, check=False)
    assert result.returncode == 0, result.stderr
