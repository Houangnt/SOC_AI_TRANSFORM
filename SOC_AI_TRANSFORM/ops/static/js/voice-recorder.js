// Shared browser capture: PCM WAV works with both local ASR backends.
// The browser requests microphone access only after an explicit button click.
async function startWavRecorder(maxSeconds, onLimit){
  if(!navigator.mediaDevices?.getUserMedia)
    throw new Error("Micro cần trình duyệt hỗ trợ ghi âm tại localhost hoặc HTTPS.");
  let stream=null, context=null, source=null, node=null, chunks=[], frames=0, stopped=false;
  function release(){
    if(node){node.onaudioprocess=null; node.disconnect();}
    if(source) source.disconnect();
    if(stream) stream.getTracks().forEach(track=>{track.onended=null; track.stop();});
    if(context) context.close().catch(()=>{});
  }
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1},video:false});
    context=new (window.AudioContext || window.webkitAudioContext)();
    await context.resume();
    source=context.createMediaStreamSource(stream);
    // Match the existing dashboard mic capture, with a bounded recording buffer.
    node=context.createScriptProcessor(4096,1,1);
    const maxFrames=Math.min(Math.floor(context.sampleRate*maxSeconds),
      Math.floor((16*1024*1024-44)/2));
    let notified=false;
    const finish=()=>{if(!notified&&!stopped){notified=true; onLimit();}};
    node.onaudioprocess=event=>{
      if(stopped || notified) return;
      const input=event.inputBuffer.getChannelData(0);
      const count=Math.min(input.length,maxFrames-frames);
      if(count>0){chunks.push(new Float32Array(input.subarray(0,count))); frames+=count;}
      if(frames>=maxFrames) finish();
    };
    stream.getAudioTracks().forEach(track=>{track.onended=finish;});
    source.connect(node); node.connect(context.destination);
    return {
      get seconds(){return frames/context.sampleRate;},
      stop(){
        if(stopped) return null;
        stopped=true; release();
        const blob=encodeWAV(chunks,context.sampleRate); chunks=[];
        return blob;
      }
    };
  } catch(error){release(); throw error;}
}

// float32 chunks → 16-bit PCM mono WAV blob
function encodeWAV(chunks, rate){
  const count=chunks.reduce((sum,chunk)=>sum+chunk.length,0);
  const buffer=new ArrayBuffer(44+count*2), view=new DataView(buffer);
  const str=(offset,text)=>{for(let i=0;i<text.length;i++) view.setUint8(offset+i,text.charCodeAt(i));};
  str(0,"RIFF"); view.setUint32(4,36+count*2,true); str(8,"WAVE"); str(12,"fmt ");
  view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true);
  view.setUint32(24,rate,true); view.setUint32(28,rate*2,true);
  view.setUint16(32,2,true); view.setUint16(34,16,true);
  str(36,"data"); view.setUint32(40,count*2,true);
  let offset=44;
  for(const chunk of chunks) for(const sample of chunk){
    const value=Math.max(-1,Math.min(1,sample));
    view.setInt16(offset,value<0?value*32768:value*32767,true); offset+=2;
  }
  return new Blob([view],{type:"audio/wav"});
}
