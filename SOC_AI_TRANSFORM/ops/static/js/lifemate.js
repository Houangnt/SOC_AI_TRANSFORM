// LifeMate uses the official sample environment; it never posts to /api/chat.
const LM = {started:false, ready:null, meta:null, tab:"run", split:"public_test", samples:[],
  sampleId:"", sample:null, text:"", loading:false, busy:false, phase:"",
  skills:[], tools:[], result:null, error:"", skill:null, filter:"", request:0,
  catalog:null, toolFilter:"", onlyEnabled:true, asrBusy:false, asrTranscripts:null,
  asrResult:null, audioFile:null, audioPending:false, audioURL:null};
const LM_MIC={starting:false,recorder:null,timer:null,token:0};

function lifeMateMicActive(){return LM_MIC.starting || !!LM_MIC.recorder;}

function lifeMateCancelMic(){
  ++LM_MIC.token;
  if(LM_MIC.recorder) LM_MIC.recorder.stop();
  clearInterval(LM_MIC.timer);
  LM_MIC.starting=false; LM_MIC.recorder=null; LM_MIC.timer=null;
}

async function lifeMateStartMic(){
  if(!LM.sample || LM.busy || LM.loading || LM.asrBusy || lifeMateMicActive()) return;
  const token=++LM_MIC.token;
  LM_MIC.starting=true; LM.error=""; LM.phase="Đang xin quyền sử dụng micro…";
  lifeMatePaint();
  try {
    const recorder=await startWavRecorder(LM.meta.asr.max_seconds,lifeMateFinishMic);
    // Permission can resolve after navigation/cancellation. Release the mic immediately.
    if(token!==LM_MIC.token){recorder.stop(); return;}
    LM_MIC.recorder=recorder; LM_MIC.starting=false;
    LM.phase="Đang ghi âm. Nói yêu cầu rồi bấm Dừng & nhận dạng.";
    LM_MIC.timer=setInterval(()=>{
      const timer=document.getElementById("lm-mic-timer");
      if(timer && LM_MIC.recorder) timer.textContent=Math.floor(LM_MIC.recorder.seconds)+" giây";
    },250);
  } catch(error){
    if(token===LM_MIC.token){
      LM_MIC.starting=false; LM.phase="";
      LM.error=error.name==="NotAllowedError" ? "Micro bị chặn. Cho phép Microphone trong trình duyệt rồi thử lại."
        : error.name==="NotFoundError" ? "Không tìm thấy micro. Hãy kết nối micro rồi thử lại."
        : "Không ghi âm được: "+error.message;
    }
  }
  lifeMatePaint();
}

async function lifeMateFinishMic(){
  if(!LM_MIC.recorder) return;
  const seconds=LM_MIC.recorder.seconds, blob=LM_MIC.recorder.stop();
  LM_MIC.recorder=null; clearInterval(LM_MIC.timer); LM_MIC.timer=null;
  if(seconds<0.25){LM.error="Bản ghi quá ngắn. Hãy nói ít nhất một câu rồi dừng."; LM.phase=""; lifeMatePaint(); return;}
  lifeMateAudioFile(new File([blob],"voice-"+Date.now()+".wav",{type:"audio/wav"}));
  await lifeMateRecognize("live");
}

function lifeMateASR(){
  const sample=LM.sample, meta=LM.meta.asr;
  if(!sample || !meta) return "";
  const disabled=LM.busy||LM.loading||LM.asrBusy||lifeMateMicActive();
  const audioURL=LM.audioURL || "/api/lifemate/audio?split="+encodeURIComponent(LM.split)+"&id="+encodeURIComponent(LM.sampleId);
  return `<div class="lm-asr"><div class="lm-row"><b>Audio → văn bản</b><span class="meta">${esc(meta.name)}</span></div>
    <div class="lm-actions"><button class="save ${LM_MIC.recorder?'rec':''}" onclick="${LM_MIC.recorder?'lifeMateFinishMic()':'lifeMateStartMic()'}" ${LM_MIC.recorder?'':disabled?'disabled':''}>${LM_MIC.recorder?'Dừng & nhận dạng':LM_MIC.starting?'Đang mở micro…':'Ghi âm bằng micro'}</button>
      ${lifeMateMicActive()?`<span id="lm-mic-timer" class="meta" role="status">${LM_MIC.recorder?Math.floor(LM_MIC.recorder.seconds)+' giây':'Đang xin quyền…'}</span><button class="sessbtn" onclick="lifeMateCancelMic(); LM.phase=''; lifeMatePaint()">Huỷ ghi âm</button>`:""}</div>
    <div class="meta">Bấm ghi âm, cho phép micro và nói yêu cầu. Dừng để chuyển giọng nói thành văn bản; agent chỉ chạy khi bạn bấm Chạy yêu cầu.</div>
    ${LM.audioURL||sample.audio_available?`<audio controls preload="none" src="${esc(audioURL)}" aria-label="${LM.audioURL?'Nghe bản ghi đã chọn':'Nghe audio của mẫu'}"></audio>`:""}
    <label class="lm-field">Thay audio câu hiện tại (tuỳ chọn)
      <input type="file" accept=".wav,.flac,.ogg" aria-label="Audio ASR" onchange="lifeMateAudioFile(this.files[0])" ${disabled?"disabled":""}></label>
    <div class="meta">${LM.audioFile?esc(LM.audioFile.name):"Dùng audio của mẫu đã chọn"} · WAV, FLAC, OGG · tối đa 16 MB / ${meta.max_seconds} giây.
      Audio lịch sử vẫn lấy từ mẫu. ASR chạy trên máy này; lần đầu có thể cần tải model.</div>
    <div class="lm-actions"><button class="save" onclick="lifeMateRecognize('live')" ${disabled||!meta.adapter_available?"disabled":""}>${LM.asrBusy?"Đang nhận dạng…":"Chạy ASR từ audio"}</button>
      <button class="sessbtn" onclick="lifeMateRecognize('saved')" ${disabled||!sample.saved_asr_available||LM.audioFile?"disabled":""}>Dùng prediction có sẵn</button></div>
    ${!meta.adapter_available?'<div class="lm-error">Chưa tìm thấy checkpoint ASR. Kiểm tra cấu hình đường dẫn adapter.</div>':""}
    <div class="meta">${meta.saved_predictions} prediction trong evaluation_improved_v2. ${LM.asrBusy?"Đang xử lý câu hiện tại và lịch sử; có thể mất vài phút trên CPU.":"Nhận dạng xong, kiểm tra transcript bên dưới rồi bấm Chạy yêu cầu."}</div>
    ${LM.asrResult?`<details><summary>Transcript ASR (${LM.asrResult.clips.length} audio · ${LM.asrResult.mode==="saved"?"có sẵn":"nhận dạng mới"})</summary><pre>${esc(JSON.stringify(LM.asrResult.clips,null,2))}</pre></details>`:""}
    </div>`;
}

function lifeMateAudioFile(file){
  if(lifeMateMicActive()) return;
  LM.error="";
  if(file && file.size>16*1024*1024){LM.error="Audio vượt quá 16 MB"; file=null;}
  LM.audioFile=file||null;
  if(LM.audioURL) URL.revokeObjectURL(LM.audioURL);
  LM.audioURL=file instanceof Blob?URL.createObjectURL(file):null;
  LM.audioPending=!!file;
  LM.phase=file?"Hãy chạy ASR để nhận dạng file vừa chọn":"";
  lifeMatePaint();
}

async function lifeMateRecognize(mode){
  if(!LM.sample || LM.busy || LM.loading || LM.asrBusy || lifeMateMicActive()) return;
  const request=LM.request, payload={split:LM.split,sample_id:LM.sampleId,mode};
  LM.asrBusy=true; LM.error=""; LM.result=null; LM.skills=[]; LM.tools=[]; LM.phase="";
  lifeMatePaint();
  try {
    if(mode==="live" && LM.audioFile){
      payload.audio_base64=await new Promise((resolve,reject)=>{
        const reader=new FileReader();
        reader.onload=()=>resolve(reader.result.split(",")[1]);
        reader.onerror=()=>reject(new Error("Không đọc được file audio"));
        reader.readAsDataURL(LM.audioFile);
      });
    }
    const response=await fetch("/api/lifemate/asr",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!response.ok) throw new Error("Không chạy được ASR (HTTP "+response.status+")");
    const data=await response.json();
    if(data.error) throw new Error(data.error);
    if(request!==LM.request) return;
    LM.text=data.text; LM.asrTranscripts=data.transcripts; LM.asrResult=data;
    LM.audioPending=false;
    LM.sample={...LM.sample,text:data.text,history:data.history,transcript_error:""};
    LM.phase="ASR hoàn tất · kiểm tra transcript trước khi chạy agent";
  } catch(e){if(request===LM.request) LM.error=e.message;}
  finally {LM.asrBusy=false; lifeMatePaint();}
}

function lifeMatePickers(){
  return `<div class="lm-pickers"><label class="lm-field">Bộ dữ liệu<select aria-label="Bộ dữ liệu" onchange="lifeMateSetSplit(this.value)" ${LM.busy||LM.asrBusy||lifeMateMicActive()?"disabled":""}>
    ${LM.meta.splits.map(s=>`<option value="${esc(s)}" ${s===LM.split?"selected":""}>${esc(s)}</option>`).join("")}</select></label>
    <label class="lm-field">Mẫu thử<select aria-label="Mẫu thử" onchange="lifeMateSelectSample(this.value)" ${LM.busy||LM.asrBusy||LM.loading||lifeMateMicActive()?"disabled":""}>
    ${LM.samples.map(s=>`<option value="${esc(s.id)}" ${s.id===LM.sampleId?"selected":""}>${esc(s.id)}</option>`).join("")}</select></label></div>`;
}

function lifeMateCatalogCards(){
  if(!LM.catalog) return `<div class="meta">Đang đọc catalog tool của BTC…</div>`;
  const query=LM.toolFilter.toLowerCase();
  return LM.catalog.tools.filter(t=>(!LM.onlyEnabled || t.enabled) &&
    (t.name+" "+(t.description||"")).toLowerCase().includes(query)).map(t=>
    `<details class="card"><summary><code>${esc(t.name)}</code> · ${esc(t.kind||"tool")}
      <span class="meta">${t.enabled?"Được phép trong mẫu":"Không có trong mẫu"}</span></summary>
      <p>${esc(t.description||"")}</p><pre>${esc(JSON.stringify(t.parameters,null,2))}</pre>
      ${t.returns?`<div class="meta">Trả về: ${esc(t.returns)}</div>`:""}</details>`).join("")
    || `<div class="meta">Không có tool khớp bộ lọc.</div>`;
}

function lifeMateFilterToolCatalog(value){
  LM.toolFilter=value;
  document.getElementById("lm-tool-catalog").innerHTML=lifeMateCatalogCards();
}
function lifeMateToolScope(value){LM.onlyEnabled=value; lifeMateFilterToolCatalog(LM.toolFilter);}

function lifeMateSkillCards(){
  if (!LM.meta) return "";
  const fold = s => String(s).normalize("NFD").replace(/\p{Diacritic}/gu, "")
    .toLowerCase().replaceAll("đ", "d");
  const query = fold(LM.filter);
  const all = [{id:"dieu-phoi-nghiep-vu", title:"Điều phối nghiệp vụ",
    description:"Hiểu điều kiện, sửa lời và phối hợp các nghiệp vụ."}, ...LM.meta.skills];
  return all.filter(s => fold(s.title+" "+s.description).includes(query)).map(s =>
    `<button class="lm-skill card" data-skill="${esc(s.id)}" onclick="lifeMateOpenSkill(this.dataset.skill)">
      <b>${esc(s.title)}</b><span class="meta">${esc(s.description)}</span></button>`).join("")
    || `<div class="meta">Không tìm thấy skill phù hợp.</div>`;
}

function lifeMateTools(){
  return LM.tools.map((call,i) => {
    let output = call.output, status = "Đã trả kết quả", bad = false;
    try {
      output = JSON.parse(output);
      if (output.ok === false){status = "Bị từ chối"; bad = true;}
      else if (output.done === false) status = "Chưa hoàn tất thao tác";
    } catch(e){}
    return `<div class="card lm-call"><div class="lm-row"><b>${i+1}. ${esc(call.tool)}</b>
      <span class="meta ${bad?"lm-error":""}">${esc(status)}</span></div>
      <details><summary>Tham số và kết quả</summary><pre>${esc(JSON.stringify({arguments:call.args, result:output},null,2))}</pre></details></div>`;
  }).join("");
}

function lifeMateView(){
  let content = "";
  if (!LM.meta){
    content = `<div class="card">${esc(LM.error || "Đang nạp bộ skill LifeMate…")}</div>`;
  } else if (!LM.meta.available){
    content = `<div class="card lm-error">${esc(LM.error || "Chưa tìm thấy bộ dữ liệu BTC. Cấu hình SOC_AI_TRANSFORM_LIFEMATE_DATA_ROOT trong .env rồi khởi động lại dashboard.")}</div>`;
  } else if (LM.tab === "tools"){
    content=`<div class="card">${lifeMatePickers()}
      <div class="meta">Catalog chính thức của ${esc(LM.split)}${LM.catalog?": "+LM.catalog.tools.length+" tool; "+LM.catalog.enabled_count+" tool được phép cho "+esc(LM.sampleId):""}.</div>
      <p>Agent chỉ được gọi tool của mẫu đã chọn, cùng sys.ask_missing_info.</p></div>
      <label class="lm-field">Tìm tool<input value="${esc(LM.toolFilter)}" oninput="lifeMateFilterToolCatalog(this.value)" placeholder="Ví dụ: contacts, banking.transfer, ride_hailing"></label>
      <label><input type="checkbox" ${LM.onlyEnabled?"checked":""} onchange="lifeMateToolScope(this.checked)"> Chỉ hiện tool được phép trong mẫu</label>
      <div id="lm-tool-catalog">${lifeMateCatalogCards()}</div>`;
  } else if (LM.tab === "skills"){
    content = `<label class="lm-field">Tìm nghiệp vụ<input value="${esc(LM.filter)}" oninput="lifeMateFilterSkills(this.value)" placeholder="Ví dụ: danh bạ, chuyển tiền, đặt xe"></label>
      <div class="lm-skills" id="lm-skill-list">${lifeMateSkillCards()}</div>
      <div id="lm-skill-detail">${LM.skill ? `<h2>${esc(LM.skill.id)}</h2><div class="card"><pre>${esc(LM.skill.instructions)}</pre></div>` : ""}</div>`;
  } else {
    const sample = LM.sample, context = sample && sample.context;
    const appNames = context ? Object.keys(context.installed_apps||{}) : [];
    content = `<div class="lm-run-grid"><section class="card lm-editor">
      <div class="section-head"><h2>Yêu cầu thực thi</h2><span class="meta">${esc(LM.split)}</span></div>
      ${lifeMatePickers()}
      ${lifeMateASR()}
      <label class="lm-field">Nội dung yêu cầu<textarea id="lm-text" rows="5" ${LM.busy||LM.asrBusy||LM.loading||lifeMateMicActive()?"disabled":""}
        oninput="lifeMateEditText(this.value)" placeholder="Nhập hoặc sửa transcript trước khi chạy…">${esc(LM.text)}</textarea></label>
      ${sample && sample.transcript_error ? `<div class="lm-error">Thiếu transcript lịch sử: ${esc(sample.transcript_error)}</div>` : ""}
      <div class="lm-actions"><button class="save" id="lm-run" onclick="lifeMateRun()" ${!lifeMateCanRun()?"disabled":""}>${LM.busy?"Đang chạy…":"Chạy yêu cầu"}</button>
        <span class="meta">${esc(LM.loading?"Đang nạp mẫu…":LM.phase)}</span></div>
      <div class="meta lm-disclosure">Transcript, ngữ cảnh, lịch sử và kết quả tool được gửi tới ${esc(LM.meta.provider)}. Thao tác thực hiện trong môi trường giả lập.</div>
    </section><aside class="card lm-context"><div class="section-head"><h2>Ngữ cảnh mẫu</h2></div>
      ${context ? `<div class="context-label">Mã mẫu</div><div class="context-value">${esc(LM.sampleId)}</div>
        <div class="context-label">Thời điểm</div><div class="context-value">${esc(context.current_time)}<br>${esc(context.timezone)}</div>
        <div class="context-label">Ứng dụng khả dụng</div><div class="lm-apps">${appNames.map(a=>`<span>${esc(a)}</span>`).join("")}</div>
        <div class="context-label">Tool được phép</div><div class="context-value">${LM.catalog?LM.catalog.enabled_count:"—"} tool trong mẫu này</div>
        <details><summary>Ngữ cảnh và lịch sử (${(sample.history||[]).length} lượt)</summary><pre>${esc(JSON.stringify({context,history:sample.history},null,2))}</pre></details>` : '<div class="meta">Chọn mẫu để xem ngữ cảnh.</div>'}
    </aside></div>
    ${LM.error ? `<div class="card lm-error" role="alert">${esc(LM.error)}</div>` : ""}
    ${LM.skills.length ? `<h2>Nghiệp vụ được chọn</h2><div class="lm-apps">${LM.skills.map(id=>`<button class="sessbtn" data-skill="${esc(id)}" onclick="lifeMateOpenSkill(this.dataset.skill)">${esc((LM.meta.skills.find(s=>s.id===id)||{}).title||id)}</button>`).join("")}</div>` : ""}
    ${LM.tools.length ? `<h2>Nhật ký gọi tool</h2>${lifeMateTools()}` : LM.busy ? `<div class="card meta" role="status">Đang chọn nghiệp vụ và suy luận…</div>` : ""}
    ${LM.result ? `<h2>Kết quả thực thi</h2><div class="card">
      ${LM.result.reply ? `<div>${renderMarkdown(LM.result.reply)}</div>` : ""}
      ${LM.result.submission ? `<div class="meta lm-hash">Mã xác nhận trạng thái · state_hash</div><code class="lm-hash-value">${esc(LM.result.submission.state_hash)}</code>
        <details><summary>JSON nộp bài${LM.result.error?" — lượt chạy chưa hoàn tất":""}</summary><pre>${esc(JSON.stringify(LM.result.submission,null,2))}</pre></details>
        <button class="save" onclick="lifeMateDownload()">Tải submission.jsonl</button>` : ""}
      <div class="meta lm-disclosure">${LM.result.error ? "Có lỗi; kết quả chứa các call đã thực hiện trước khi dừng." : "Đã kết thúc lượt chạy. Đây chưa phải điểm chấm của BTC."}</div>
    </div>` : !LM.busy ? `<div class="lm-empty-result"><b>Kết quả sẽ xuất hiện tại đây</b>Chọn mẫu, kiểm tra nội dung rồi bấm Chạy yêu cầu.<br>Bạn có thể xem từng tool call và tải file kết quả sau khi chạy.</div>` : ""}`;
  }
  return `<div id="lifemate-root"><div class="card lm-intro"><span class="eyebrow">LIFEMATE WORKSPACE</span>
    <b>${LM.tab==="skills"?"Thư viện nghiệp vụ":LM.tab==="tools"?"Công cụ thực thi":"Từ yêu cầu đến kết quả"}</b>
    <span>${LM.tab==="skills"?"Tra cứu cách agent xử lý từng nghiệp vụ.":LM.tab==="tools"?"Xem schema và quyền dùng tool theo từng mẫu.":"Kiểm tra nội dung, chạy agent và theo dõi hành động trên môi trường giả lập."}</span></div>
    <div class="subtabs"><button class="subtab ${LM.tab==="run"?"on":""}" onclick="lifeMateSetTab('run')">Chạy thử</button>
      <button class="subtab ${LM.tab==="skills"?"on":""}" onclick="lifeMateSetTab('skills')">Nghiệp vụ${LM.meta?" ("+(LM.meta.skills.length+1)+")":""}</button>
      <button class="subtab ${LM.tab==="tools"?"on":""}" onclick="lifeMateSetTab('tools')">Thư viện tool</button></div>${content}</div>`;
}

VIEWS.lifemate = lifeMateView;

function lifeMatePaint(){
  lifeMateSyncChatScope();
  if (!document.getElementById("lifemate-root")) return;
  const main = document.querySelector("main"), y = main.scrollTop;
  document.getElementById("view").innerHTML = lifeMateView();
  main.scrollTop = y;
}
function lifeMateSetTab(tab){if(tab!=="run") lifeMateCancelMic(); LM.tab=tab; location.hash=tab==="run"?"#lifemate":"#lifemate/"+tab; lifeMatePaint();}
function lifeMateFilterSkills(value){
  LM.filter=value;
  document.getElementById("lm-skill-list").innerHTML=lifeMateSkillCards();
}
function lifeMateCanRun(){return !!(LM.sample && !LM.sample.transcript_error && LM.text.trim() && !LM.busy && !LM.asrBusy && !LM.loading && !LM.audioPending && !lifeMateMicActive());}
function lifeMateEditText(value){
  LM.text=value;
  const button=document.getElementById("lm-run"); if(button) button.disabled=!lifeMateCanRun();
}
async function lifeMateJSON(url){
  const response=await fetch(url), data=await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Không đọc được dữ liệu LifeMate");
  return data;
}
function lifeMateInit(){
  if (LM.ready) return LM.ready;
  LM.started=true;
  LM.ready=(async()=>{
    try {
      LM.meta=await lifeMateJSON("/api/lifemate");
      try {
        const saved=JSON.parse(localStorage.getItem("SOC_AI_TRANSFORM_lifemate_scope"));
        if(saved && LM.meta.splits.includes(saved.split)){LM.split=saved.split; LM.sampleId=saved.sample_id;}
      } catch(e){}
      if (!LM.meta.splits.includes(LM.split)) LM.split=LM.meta.splits[0];
      if (LM.split) await lifeMateSetSplit(LM.split);
    } catch(e){LM.error=e.message;}
    lifeMatePaint();
  })();
  return LM.ready;
}
function lifeMateSyncChatScope(){
  const badge=document.getElementById("chat-scope");
  if(badge) badge.textContent=LM.sample ? LM.split+" / "+LM.sampleId : "Chọn mẫu LifeMate";
  const available=document.getElementById("overview-available-tools");
  if(available) available.textContent=LM.sample && LM.catalog && !LM.loading ? LM.catalog.enabled_count : "—";
  const scope=document.getElementById("overview-tool-scope");
  if(scope) scope.textContent=LM.sample ? LM.split+" / "+LM.sampleId : "chọn ở LifeMate";
  const sample=document.getElementById("overview-sample");
  if(sample && typeof overviewSample==="function") sample.innerHTML=overviewSample();
  const skills=document.getElementById("overview-skill-count");
  if(skills) skills.textContent=LM.meta ? LM.meta.skills.length+1 : "—";
  const toolCount=document.getElementById("n-tools");
  if(toolCount) toolCount.textContent=LM.catalog ? LM.catalog.tools.length : "";
}
async function lifeMateChatScope(){
  await lifeMateInit();
  return LM.sample ? {split:LM.split,sample_id:LM.sampleId} : null;
}
async function lifeMateSetSplit(split){
  if (LM.busy || LM.asrBusy || lifeMateMicActive()) return;
  LM.split=split; LM.sample=null; LM.catalog=null; LM.loading=true; LM.error=""; LM.result=null;
  lifeMatePaint();
  try {
    const data=await lifeMateJSON("/api/lifemate/samples?split="+encodeURIComponent(split));
    if (LM.split!==split) return;
    LM.samples=data.samples;
    const preferred=LM.samples.some(s=>s.id===LM.sampleId)?LM.sampleId:
      split==="public_test"?"public_0002":"train_0001";
    const id=LM.samples.some(s=>s.id===preferred)?preferred:(LM.samples[0]||{}).id;
    if (id) await lifeMateSelectSample(id);
    else throw new Error("Bộ dữ liệu không có mẫu nào");
  } catch(e){LM.error=e.message; LM.loading=false; lifeMatePaint();}
}
async function lifeMateSelectSample(id){
  if (LM.busy || LM.asrBusy || lifeMateMicActive()) return;
  const request=++LM.request, split=LM.split;
  LM.sampleId=id; LM.sample=null; LM.catalog=null; LM.loading=true; LM.error=""; LM.result=null;
  LM.asrTranscripts=null; LM.asrResult=null; LM.audioFile=null; LM.audioPending=false;
  if(LM.audioURL) URL.revokeObjectURL(LM.audioURL); LM.audioURL=null;
  LM.skills=[]; LM.tools=[]; LM.phase=""; lifeMatePaint();
  try {
    const data=await lifeMateJSON("/api/lifemate/sample?split="+encodeURIComponent(split)+"&id="+encodeURIComponent(id));
    if (request!==LM.request || split!==LM.split) return;
    LM.sample=data; LM.text=data.text;
    const catalog=await lifeMateJSON("/api/lifemate/tools?split="+encodeURIComponent(split)+"&id="+encodeURIComponent(id));
    if (request!==LM.request || split!==LM.split) return;
    LM.catalog=catalog;
    try {localStorage.setItem("SOC_AI_TRANSFORM_lifemate_scope",JSON.stringify({split,sample_id:id}));} catch(e){}
  } catch(e){if(request===LM.request) LM.error=e.message;}
  if(request===LM.request){LM.loading=false; lifeMatePaint();}
}
async function lifeMateOpenSkill(id){
  try {
    LM.skill=await lifeMateJSON("/api/lifemate/skill?id="+encodeURIComponent(id));
    lifeMateSetTab("skills");
    document.getElementById("lm-skill-detail").scrollIntoView({behavior:"smooth",block:"start"});
  } catch(e){LM.error=e.message; lifeMatePaint();}
}
function lifeMateApplyEvent(event){
  if(event.kind==="business_skills"){LM.skills=event.skills; LM.phase="Đã chọn nghiệp vụ";}
  if(event.kind==="llm") LM.phase="Đang suy luận · vòng "+event.iteration;
  if(event.kind==="tool"){LM.tools.push(event); LM.phase="Đã gọi "+event.tool;}
  if(event.kind==="done"){
    LM.busy=false; LM.result=event; LM.error=event.error||"";
    LM.skills=event.skills||LM.skills; LM.tools=event.tools||LM.tools;
    LM.phase=event.error?"Lượt chạy có lỗi":"Đã kết thúc lượt chạy";
  }
  lifeMatePaint();
}
async function lifeMateRun(){
  if(!lifeMateCanRun()) return;
  LM.busy=true; LM.error=""; LM.result=null; LM.skills=[]; LM.tools=[]; LM.phase="Đang khởi động…";
  const payload={run_id:crypto.randomUUID(),split:LM.split,sample_id:LM.sampleId,text:LM.text};
  if(LM.asrTranscripts) payload.asr_transcripts=LM.asrTranscripts;
  lifeMatePaint();
  try {
    const response=await fetch("/api/lifemate/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!response.ok) throw new Error("Không bắt đầu được lượt chạy");
    const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer="";
    for(;;){
      const chunk=await reader.read(); if(chunk.done) break;
      buffer+=decoder.decode(chunk.value,{stream:true});
      let end;
      while((end=buffer.indexOf("\n\n"))>=0){
        const frame=buffer.slice(0,end); buffer=buffer.slice(end+2);
        if(frame.startsWith("data:")) lifeMateApplyEvent(JSON.parse(frame.slice(5).trim()));
      }
    }
    if(LM.busy) throw new Error("Kết nối đã ngắt trước khi nhận kết quả. Không tự chạy lại; log được lưu local sau khi lượt chạy kết thúc.");
  } catch(e){LM.error=e.message; LM.busy=false; LM.phase="Kết nối kết thúc"; lifeMatePaint();}
}
function lifeMateDownload(){
  if(!LM.result || !LM.result.submission) return;
  const blob=new Blob([JSON.stringify(LM.result.submission)+"\n"],{type:"application/x-ndjson"});
  const url=URL.createObjectURL(blob), link=document.createElement("a");
  link.href=url; link.download=LM.result.submission.id+"-submission.jsonl";
  link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
