(() => {
  const phases = [
    {n:1,title:"Research and System Design",weeks:"Weeks 1–3",status:"complete",
     desc:"Literature review, system architecture, typed schemas, versioned state machines.",
     deliverables:["Literature review","System architecture","Typed schemas","Versioned state machines"]},
    {n:2,title:"Gateway and Evidence Store",weeks:"Weeks 4–6",status:"in_progress",
     desc:"ToolTruth gateway, persistent evidence store, state versions, timestamps, provenance.",
     deliverables:["ToolTruth gateway","Persistent evidence store","State versions","Timestamps","Provenance"]},
    {n:3,title:"Domain Simulators and Fault Injection",weeks:"Weeks 7–9",status:"planned",
     desc:"E-commerce/Travel/DevOps simulators, fault injection, stale data, duplicates.",
     deliverables:["E-commerce simulator","Travel simulator","DevOps simulator","Fault injection","Stale data and duplicates"]},
    {n:4,title:"Temporal Verification Engine",weeks:"Weeks 10–12",status:"planned",
     desc:"Freshness, conflicts, ordering, retries, race conditions, idempotency, partial failures.",
     deliverables:["Freshness checks","Conflict detection","Ordering verification","Retry handling","Race conditions","Idempotency","Partial failure compensation"]},
    {n:5,title:"SDK, API and Web Interface",weeks:"Weeks 13–15",status:"planned",
     desc:"Reusable SDK/API, hosted interface, evidence trails, decision certificates.",
     deliverables:["Reusable SDK/API","Hosted interface","Evidence trails","Decision certificates"]},
    {n:6,title:"Benchmark and Comparative Evaluation",weeks:"Weeks 13–16",status:"planned",
     desc:"75 benchmark tasks, five-way comparison, evaluation metrics.",
     deliverables:["75 benchmark tasks","Five-way comparison","Evaluation metrics"]},
    {n:7,title:"Final Validation and Deployment",weeks:"Weeks 16–17",status:"planned",
     desc:"Performance evaluation, deployment, documentation, final validation.",
     deliverables:["Performance evaluation","Deployment","Documentation","Final validation"]}
  ];

  const schedule = [
    ["m1","M1 · Research and System Design","2026-08-10","2026-08-30",100,""],
    ["m1a","Literature review","2026-08-10","2026-08-16",100,"m1"],
    ["m1b","State machine design","2026-08-17","2026-08-23",100,"m1a"],
    ["m1c","Schema design","2026-08-24","2026-08-30",100,"m1b"],
    ["m2","M2 · Gateway and Evidence Store","2026-08-31","2026-09-20",60,"m1"],
    ["m2a","Gateway interceptor","2026-08-31","2026-09-06",100,"m1c"],
    ["m2b","Evidence store DB","2026-09-07","2026-09-13",70,"m2a"],
    ["m2c","Provenance tracking","2026-09-14","2026-09-20",0,"m2b"],
    ["m3","M3 · Domain Simulators and Fault Injection","2026-09-21","2026-10-11",0,"m2"],
    ["m3a","E-commerce simulator","2026-09-21","2026-09-27",0,"m2"],
    ["m3b","Travel simulator","2026-09-28","2026-10-04",0,"m3a"],
    ["m3c","DevOps simulator","2026-09-28","2026-10-04",0,"m3a"],
    ["m3d","Fault injector","2026-10-05","2026-10-11",0,"m3b,m3c"],
    ["m4","M4 · Temporal Verification Engine","2026-10-12","2026-11-01",0,"m3"],
    ["m4a","Freshness checks","2026-10-12","2026-10-18",0,"m3d"],
    ["m4b","Conflict detection","2026-10-12","2026-10-18",0,"m3d"],
    ["m4c","Ordering verification","2026-10-19","2026-10-25",0,"m4a,m4b"],
    ["m4d","Compensation logic","2026-10-26","2026-11-01",0,"m4c"],
    ["m5","M5 · SDK, API and Web Interface","2026-11-02","2026-11-22",0,"m4"],
    ["m5a","SDK package","2026-11-02","2026-11-08",0,"m4d"],
    ["m5b","REST API","2026-11-09","2026-11-15",0,"m5a"],
    ["m5c","Web UI for certificates","2026-11-16","2026-11-22",0,"m5b"],
    ["m6","M6 · Benchmark and Comparative Evaluation","2026-11-02","2026-11-29",0,"m4"],
    ["m6a","Task classification","2026-11-02","2026-11-08",0,"m4d"],
    ["m6b","Baseline runners","2026-11-09","2026-11-15",0,"m6a"],
    ["m6c","Report generation","2026-11-16","2026-11-29",0,"m6b"],
    ["m7","M7 · Final Validation and Deployment","2026-11-30","2026-12-13",0,"m5,m6"],
    ["m7a","Integration tests","2026-11-30","2026-12-06",0,"m5c,m6c"],
    ["m7b","Deployment","2026-12-07","2026-12-10",0,"m7a"],
    ["m7c","Documentation","2026-12-07","2026-12-13",0,"m7a"]
  ];

  function renderCards() {
    document.getElementById("milestones").innerHTML = phases.map(p => `
      <article class="milestone-card glass" data-status="${p.status}">
        <div class="milestone-number">${p.n}</div>
        <div class="milestone-content">
          <div class="milestone-top"><span class="milestone-week">${p.weeks}</span><span class="milestone-status" data-status="${p.status}">${p.status.replace("_"," ")}</span></div>
          <h2>${p.title}</h2><p>${p.desc}</p>
          <ul class="milestone-deliverables">${p.deliverables.map(x=>`<li>${x}</li>`).join("")}</ul>
        </div>
      </article>`).join("");
  }

  function renderGantt() {
    const host=document.getElementById("gantt");
    if (!host || typeof Gantt === "undefined") {
      host.innerHTML='<p class="muted">Frappe Gantt could not be loaded. Check the network connection and refresh.</p>';
      return;
    }
    const tasks=schedule.map(([id,name,start,end,progress,dependencies]) => ({
      id,name,start,end,progress,dependencies:dependencies || undefined
    }));
    let chart=new Gantt("#gantt",tasks,{view_mode:"Week",date_format:"YYYY-MM-DD",today_button:true,
      custom_popup_html:task=>`<div class="gantt-popup"><strong>${task.name}</strong><span>${task.start} → ${task.end}</span><span>${task.progress}% complete</span></div>`});
    document.querySelectorAll("[data-view]").forEach(btn=>btn.addEventListener("click",()=>{
      chart.change_view_mode(btn.dataset.view);
    }));
  }
  document.addEventListener("DOMContentLoaded", () => { renderCards(); renderGantt(); });
})();