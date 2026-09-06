"""Flask ingress web UI for MedTracker.

Two views in one page:
  - Today: a phone-friendly tap list of every subject's doses with Take / Skip /
    Undo, refreshed live.
  - Manage: add/edit subjects, medications and their schedules (fixed times or
    every N hours, fractional doses) and optional inventory.

Ingress requirement: all URLs are RELATIVE (``api/foo``) and the server binds
0.0.0.0 so the Supervisor's ingress proxy can reach it.
"""
from __future__ import annotations

import logging

from flask import Flask, jsonify, request
from waitress import serve as waitress_serve

log = logging.getLogger("medtracker.web")


def create_app(controller, settings):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return PAGE, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.get("/api/model")
    def api_model():
        return jsonify(controller.model())

    @app.get("/api/config")
    def api_config_get():
        return jsonify(controller.get_config())

    @app.post("/api/config")
    def api_config_post():
        data = request.get_json(silent=True) or {}
        saved = controller.save_config(data)
        return jsonify(saved)

    @app.post("/api/action")
    def api_action():
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        sid = data.get("subject")
        mid = data.get("medication")
        ok = False
        if action == "take":
            ok = controller.take(sid, mid)
        elif action == "skip":
            ok = controller.skip(sid, mid)
        elif action == "undo":
            ok = controller.undo(sid, mid)
        elif action == "take_all":
            ok = controller.take_all_due(sid) > 0
        return jsonify({"ok": ok, "model": controller.model()})

    return app


def serve(controller, settings, host="0.0.0.0", port=8098):
    app = create_app(controller, settings)
    log.info("Web UI on http://%s:%d (ingress)", host, port)
    waitress_serve(app, host=host, port=port, threads=4, _quiet=True)


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MedTracker</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--fg:#1c1e21;--muted:#6b7280;--line:#e3e6ea;
--accent:#3b82f6;--ok:#16a34a;--due:#d97706;--over:#dc2626;--upc:#6b7280;}
@media(prefers-color-scheme:dark){:root{--bg:#111417;--card:#1b1f24;--fg:#e6e8eb;
--muted:#9aa3ad;--line:#2b3138;--accent:#4b93ff;}}
*{box-sizing:border-box}
body{margin:0;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;background:var(--bg);padding:12px 16px 0;border-bottom:1px solid var(--line);z-index:5}
h1{font-size:18px;margin:0 0 8px;display:flex;align-items:center;gap:8px}
.tabs{display:flex;gap:4px}
.tab{padding:8px 14px;border:none;background:none;color:var(--muted);font-size:14px;
cursor:pointer;border-bottom:2px solid transparent}
.tab.active{color:var(--fg);border-bottom-color:var(--accent);font-weight:600}
main{padding:16px;max-width:760px;margin:0 auto}
.hub{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:14px}
.hub .big{font-size:15px;font-weight:600}
.hub .sub{color:var(--muted);font-size:13px;margin-top:2px}
.subject{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:14px;overflow:hidden}
.subject>.head{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--line)}
.subject>.head .name{font-weight:600;display:flex;align-items:center;gap:6px}
.subject>.head .meta{color:var(--muted);font-size:12px}
.med{padding:10px 14px;border-bottom:1px solid var(--line)}
.med:last-child{border-bottom:none}
.med .row1{display:flex;align-items:center;justify-content:space-between;gap:8px}
.med .mname{font-weight:600}
.med .mline{color:var(--muted);font-size:13px;margin-top:2px}
.chip{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px;color:#fff;text-transform:uppercase;letter-spacing:.02em}
.s-upcoming{background:var(--upc)} .s-due{background:var(--due)} .s-overdue{background:var(--over)}
.s-done{background:var(--ok)} .s-none{background:var(--upc)}
.insts{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px}
.inst{font-size:11px;padding:2px 6px;border-radius:6px;border:1px solid var(--line);color:var(--muted)}
.inst.taken{color:var(--ok);border-color:var(--ok)}
.inst.skipped{text-decoration:line-through}
.inst.due{color:var(--due);border-color:var(--due)}
.inst.overdue{color:var(--over);border-color:var(--over)}
.btns{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
button.act{border:1px solid var(--line);background:var(--bg);color:var(--fg);
border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer}
button.act.take{background:var(--accent);color:#fff;border-color:var(--accent)}
button.primary{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:9px 16px;font-size:14px;cursor:pointer}
.inv{font-size:12px;color:var(--muted);margin-top:4px}
.inv.low{color:var(--over);font-weight:600}
.empty{color:var(--muted);text-align:center;padding:32px}
/* Manage */
.m-subject{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:14px}
.m-med{border:1px solid var(--line);border-radius:10px;padding:10px;margin:10px 0}
label{font-size:12px;color:var(--muted);display:block;margin:6px 0 2px}
input,select{font:inherit;padding:7px 8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);width:100%}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.trow{display:flex;gap:6px;align-items:center;margin:6px 0}
.trow input[type=time]{width:120px}.trow input[type=number]{width:90px}
.frac{display:flex;gap:4px}
.frac button{border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;padding:4px 8px;font-size:13px;cursor:pointer}
.link{background:none;border:none;color:var(--accent);cursor:pointer;font-size:13px;padding:4px}
.del{background:none;border:none;color:var(--over);cursor:pointer;font-size:13px}
.hidden{display:none}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#111;color:#fff;
padding:9px 16px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:.95}
.checkline{display:flex;align-items:center;gap:8px;margin-top:8px}.checkline input{width:auto}
</style>
</head>
<body>
<header>
  <h1>💊 MedTracker</h1>
  <div class="tabs">
    <button class="tab active" data-view="today">Today</button>
    <button class="tab" data-view="manage">Manage</button>
  </div>
</header>
<main>
  <div id="today"></div>
  <div id="manage" class="hidden"></div>
</main>
<div class="toast" id="toast"></div>
<script>
const $=(s,r=document)=>r.querySelector(s);
const el=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};
const KIND_ICON={person:"🧑",animal:"🐾",other:"🏷️"};
function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),1600);}

// ---- Tabs ----
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  b.classList.add("active");
  const v=b.dataset.view;
  $("#today").classList.toggle("hidden",v!=="today");
  $("#manage").classList.toggle("hidden",v!=="manage");
  if(v==="today")loadToday(); else loadManage();
});

// ---- Today ----
async function loadToday(){
  let m;
  try{m=await (await fetch("api/model")).json();}catch(e){$("#today").innerHTML='<div class="empty">Cannot reach the add-on.</div>';return;}
  window.MODEL_DATE=m.date;
  const root=$("#today");root.innerHTML="";
  const hub=el("div","hub");
  hub.append(el("div","big",escapeHtml(hub_line(m.hub))));
  hub.append(el("div","sub",m.hub.total_due+" due now · "+countScheduled(m)+" scheduled today"));
  root.append(hub);
  if(!m.subjects.length){root.append(el("div","empty",'No subjects yet. Add one on the <b>Manage</b> tab.'));return;}
  for(const s of m.subjects){
    const card=el("div","subject");
    const head=el("div","head");
    head.append(el("div","name",(KIND_ICON[s.kind]||"")+" "+escapeHtml(s.name)));
    const meta=el("div","meta",s.taken_today+"/"+s.scheduled_today+" taken"+(s.overdue?" · ⚠ overdue":""));
    head.append(meta);
    card.append(head);
    if(!s.medications.length){card.append(el("div","med",'<span class="mline">No medications.</span>'));}
    for(const md of s.medications){card.append(medRow(s,md));}
    if(s.due_now>0){
      const wrap=el("div","med");const b=el("button","act take","✓ Take all due ("+s.due_now+")");
      b.onclick=()=>doAction("take_all",s.id,null);wrap.append(b);card.append(wrap);
    }
    root.append(card);
  }
}
function hub_line(h){return h.next_summary;}
function countScheduled(m){return m.subjects.reduce((a,s)=>a+s.scheduled_today,0);}
function nextText(md){
  if(!md.next_due_time)return "";
  let t=md.next_due_time;
  if(md.next_due_date&&md.next_due_date!==window.MODEL_DATE){
    const dd=new Date(md.next_due_date+"T00:00:00");
    t=dd.toLocaleDateString(undefined,{weekday:"short",day:"numeric",month:"short"})+" "+md.next_due_time;
  }
  return t+(md.next_dose_label?" ("+escapeHtml(md.next_dose_label)+")":"");
}
function medRow(s,md){
  const d=el("div","med");
  const r1=el("div","row1");
  const left=el("div");
  left.append(el("div","mname",escapeHtml(md.name)));
  const nt=nextText(md);
  let line;
  if(md.active_today){line=md.dose_summary+" doses"+(nt?" · next "+nt:"");}
  else{line=nt?("Next: "+nt):"Not scheduled";}
  left.append(el("div","mline",line));
  if(md.course){left.append(el("div","mline","📅 Course: "+escapeHtml(md.course.summary)));}
  r1.append(left);
  r1.append(el("span","chip s-"+md.state,md.state));
  d.append(r1);
  if(md.active_today&&md.instances&&md.instances.length){
    const ins=el("div","insts");
    for(const i of md.instances){ins.append(el("span","inst "+i.status,i.at_time+" "+escapeHtml(i.dose_label)));}
    d.append(ins);
  }
  if(md.inventory){
    const dl=md.inventory.days_left;
    const inv=el("div","inv"+(md.inventory.low?" low":""),
      "Stock: "+md.inventory.remaining+" "+escapeHtml(md.inventory.unit)+
      (dl!=null?" · ~"+dl+" days left":"")+(md.inventory.low?" · LOW":""));
    d.append(inv);
  }
  if(md.active_today){
    const btns=el("div","btns");
    const take=el("button","act take","✓ Take");take.onclick=()=>doAction("take",s.id,md.id);
    const skip=el("button","act","Skip");skip.onclick=()=>doAction("skip",s.id,md.id);
    const undo=el("button","act","Undo");undo.onclick=()=>doAction("undo",s.id,md.id);
    btns.append(take,skip,undo);d.append(btns);
  }
  return d;
}
async function doAction(action,sid,mid){
  try{
    const r=await fetch("api/action",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({action,subject:sid,medication:mid})});
    const j=await r.json();
    toast(j.ok?"Done":"Nothing to do");
    loadToday();
  }catch(e){toast("Failed");}
}

// ---- Manage ----
let cfg={subjects:[]};
async function loadManage(){
  try{cfg=await (await fetch("api/config")).json();}catch(e){cfg={subjects:[]};}
  renderManage();
}
function renderManage(){
  const root=$("#manage");root.innerHTML="";
  const wrap=el("div");
  (cfg.subjects||[]).forEach((s,si)=>wrap.append(subjectCard(s,si)));
  root.append(wrap);
  const add=el("button","link","+ Add subject");add.onclick=()=>{cfg.subjects.push({name:"New subject",kind:"person",medications:[]});renderManage();};
  root.append(add);
  const save=el("div",null);save.style.marginTop="14px";
  const sb=el("button","primary","Save changes");sb.onclick=saveConfig;save.append(sb);
  root.append(save);
}
function subjectCard(s,si){
  const c=el("div","m-subject");
  const grid=el("div","grid");
  grid.append(field("Name",inputBind(s,"name")));
  grid.append(field("Type",selectBind(s,"kind",[["person","Person"],["animal","Animal"],["other","Other"]])));
  c.append(grid);
  const meds=el("div");
  (s.medications||[]).forEach((md,mi)=>meds.append(medCard(s,md,mi)));
  c.append(meds);
  const addm=el("button","link","+ Add medication");
  addm.onclick=()=>{s.medications=s.medications||[];s.medications.push(newMed());renderManage();};
  c.append(addm);
  const del=el("button","del","Remove subject");del.style.float="right";
  del.onclick=()=>{cfg.subjects.splice(si,1);renderManage();};
  c.append(del);
  return c;
}
function newMed(){return {name:"New medication",unit:"pill",notes:"",schedule:{type:"times",times:[{time:"08:00",dose:1}]},inventory:{track:false,count:0}};}
function medCard(s,md,mi){
  const c=el("div","m-med");
  md.schedule=md.schedule||{type:"times",times:[{time:"08:00",dose:1}]};
  md.inventory=md.inventory||{track:false,count:0};
  const g=el("div","grid3");
  g.append(field("Medication",inputBind(md,"name")));
  g.append(field("Unit",inputBind(md,"unit")));
  g.append(field("Schedule",selectBind(md.schedule,"type",[["times","Fixed times"],["interval","Every N hours"]],()=>renderManage())));
  c.append(g);
  c.append(field("Notes (optional)",inputBind(md,"notes")));
  if(md.schedule.type==="interval"){c.append(intervalEditor(md.schedule));}
  else{c.append(timesEditor(md.schedule));}
  c.append(recurrenceEditor(md));
  // inventory
  const chk=el("input");chk.type="checkbox";chk.checked=!!md.inventory.track;
  chk.onchange=()=>{md.inventory.track=chk.checked;renderManage();};
  const cl=el("label","checkline");cl.append(chk,document.createTextNode("Track inventory"));
  const invBox=el("div");invBox.append(cl);
  if(md.inventory.track){
    const inv=el("div","grid");inv.append(field("Remaining ("+escapeHtml(md.unit||"unit")+")",numberBind(md.inventory,"count")));invBox.append(inv);
  }
  c.append(invBox);
  const del=el("button","del","Remove medication");del.onclick=()=>{s.medications.splice(mi,1);renderManage();};
  c.append(del);
  return c;
}
function todayISO(){const d=new Date();return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");}
function recurrenceEditor(md){
  if(!md.recurrence)md.recurrence={type:"daily",end:{type:"forever"}};
  const rec=md.recurrence; rec.end=rec.end||{type:"forever"};
  const box=el("div");
  const mode=(rec.type==="interval")?(rec.unit==="week"?"weeks":"days"):(rec.type==="weekdays"?"weekdays":"daily");
  const modeSel=el("select");
  [["daily","Every day"],["days","Every N days"],["weeks","Every N weeks"],["weekdays","Specific weekdays"]].forEach(([v,l])=>{
    const o=el("option",null,l);o.value=v;if(v===mode)o.selected=true;modeSel.append(o);});
  modeSel.onchange=()=>{
    const v=modeSel.value;
    if(v==="daily"){rec.type="daily";delete rec.every;delete rec.unit;delete rec.weekdays;}
    else if(v==="days"){rec.type="interval";rec.unit="day";rec.every=rec.every||1;delete rec.weekdays;if(!rec.start)rec.start=todayISO();}
    else if(v==="weeks"){rec.type="interval";rec.unit="week";rec.every=rec.every||1;delete rec.weekdays;if(!rec.start)rec.start=todayISO();}
    else{rec.type="weekdays";rec.weekdays=(rec.weekdays&&rec.weekdays.length)?rec.weekdays:[0];delete rec.every;delete rec.unit;if(!rec.start)rec.start=todayISO();}
    renderManage();
  };
  box.append(field("Repeats",modeSel));
  if(rec.type==="interval"){
    box.append(field("Every (number of "+(rec.unit==="week"?"weeks":"days")+")",numberBind(rec,"every",1)));
  }
  if(rec.type==="weekdays"){
    const days=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
    const wrap=el("div","frac");rec.weekdays=rec.weekdays||[];
    days.forEach((lbl,idx)=>{
      const b=el("button",null,lbl);b.type="button";
      if(rec.weekdays.includes(idx)){b.style.background="var(--accent)";b.style.color="#fff";}
      b.onclick=()=>{const i=rec.weekdays.indexOf(idx);if(i>=0)rec.weekdays.splice(i,1);else rec.weekdays.push(idx);rec.weekdays.sort((a,c)=>a-c);renderManage();};
      wrap.append(b);
    });
    box.append(field("On days (Mon–Sun)",wrap));
  }
  const st=el("input");st.type="date";st.value=rec.start||"";st.onchange=()=>rec.start=st.value;
  box.append(field("Start date"+(rec.type==="daily"?" (optional)":""),st));
  const endSel=el("select");
  [["forever","No end"],["count","After N times"],["date","On date"]].forEach(([v,l])=>{const o=el("option",null,l);o.value=v;if((rec.end.type||"forever")===v)o.selected=true;endSel.append(o);});
  endSel.onchange=()=>{rec.end={type:endSel.value};if(endSel.value==="count")rec.end.count=6;if(endSel.value==="date")rec.end.until=todayISO();renderManage();};
  box.append(field("Ends",endSel));
  if(rec.end.type==="count"){box.append(field("Number of times",numberBind(rec.end,"count",6)));}
  if(rec.end.type==="date"){const u=el("input");u.type="date";u.value=rec.end.until||"";u.onchange=()=>rec.end.until=u.value;box.append(field("Until",u));}
  return field("Repeat / course",box);
}
function timesEditor(sch){
  sch.times=sch.times&&sch.times.length?sch.times:[{time:"08:00",dose:1}];
  const box=el("div");
  sch.times.forEach((t,ti)=>{
    const row=el("div","trow");
    const time=el("input");time.type="time";time.value=t.time||"08:00";time.onchange=()=>t.time=time.value;
    const dose=el("input");dose.type="number";dose.step="0.001";dose.min="0";dose.value=t.dose??1;dose.onchange=()=>t.dose=parseFloat(dose.value)||0;
    row.append(time,dose,fracBtns(v=>{dose.value=v;t.dose=v;}));
    const del=el("button","del","✕");del.onclick=()=>{sch.times.splice(ti,1);renderManage();};
    row.append(del);box.append(row);
  });
  const add=el("button","link","+ Add time");add.onclick=()=>{sch.times.push({time:"20:00",dose:1});renderManage();};
  box.append(add);
  return field("Times & dose",box);
}
function intervalEditor(sch){
  const box=el("div","grid");
  box.append(field("Every (hours)",numberBind(sch,"every_hours",4)));
  box.append(field("Dose each time",numberDoseBind(sch)));
  const box2=el("div","grid");
  const st=el("input");st.type="time";st.value=sch.start||"08:00";st.onchange=()=>sch.start=st.value;
  const en=el("input");en.type="time";en.value=sch.end||"22:00";en.onchange=()=>sch.end=en.value;
  box2.append(field("Start",st));box2.append(field("End",en));
  const wrap=el("div");wrap.append(box,box2);
  return field("Every N hours",wrap);
}
function fracBtns(cb){
  const f=el("div","frac");
  [["1",1],["½",0.5],["⅓",0.333],["¼",0.25],["⅛",0.125]].forEach(([lbl,v])=>{
    const b=el("button",null,lbl);b.type="button";b.onclick=()=>cb(v);f.append(b);
  });
  return f;
}
// bindings
function field(lbl,node){const w=el("div");w.append(el("label",null,lbl));w.append(node);return w;}
function inputBind(o,k){const i=el("input");i.value=o[k]||"";i.oninput=()=>o[k]=i.value;return i;}
function numberBind(o,k,def){const i=el("input");i.type="number";i.step="0.001";i.min="0";i.value=o[k]??def??0;i.oninput=()=>o[k]=parseFloat(i.value)||0;return i;}
function numberDoseBind(sch){const box=el("div");const i=el("input");i.type="number";i.step="0.001";i.min="0";i.value=sch.dose??1;i.oninput=()=>sch.dose=parseFloat(i.value)||0;box.append(i);box.append(fracBtns(v=>{i.value=v;sch.dose=v;}));return box;}
function selectBind(o,k,opts,after){const s=el("select");opts.forEach(([v,l])=>{const op=el("option",null,l);op.value=v;if(o[k]===v)op.selected=true;s.append(op);});s.onchange=()=>{o[k]=s.value;if(after)after();};return s;}
async function saveConfig(){
  try{
    const r=await fetch("api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(cfg)});
    cfg=await r.json();toast("Saved");renderManage();
  }catch(e){toast("Save failed");}
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}

loadToday();
setInterval(()=>{if(!$("#today").classList.contains("hidden"))loadToday();},15000);
</script>
</body>
</html>"""
