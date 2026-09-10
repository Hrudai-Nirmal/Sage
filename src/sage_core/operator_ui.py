"""Render Sage's dependency-free, localhost-only operator interface."""


def getOperatorHtml() -> str:
    """Return a responsive control panel that keeps conversation in Telegram."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sage Operator</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background:#0b0d0c; color:#edf3ee; }
    * { box-sizing:border-box; } body { margin:0; min-height:100vh; background:radial-gradient(circle at 85% 0,#1c382c 0,transparent 38%),#0b0d0c; }
    main { width:min(1080px,calc(100% - 32px)); margin:auto; padding:48px 0 72px; }
    header { display:flex; justify-content:space-between; gap:24px; align-items:end; margin-bottom:34px; }
    h1 { font:600 clamp(2.2rem,7vw,4.8rem)/.95 Georgia,serif; margin:0; letter-spacing:-.05em; } .eyebrow { color:#8fc6a8; letter-spacing:.18em; text-transform:uppercase; font-size:.72rem; }
    #health { color:#9cac9f; } .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }
    .card { border:1px solid #29332d; background:rgba(18,23,20,.82); border-radius:18px; padding:20px; box-shadow:0 18px 50px rgba(0,0,0,.22); }
    .card span { color:#91a097; font-size:.82rem; } .card strong { display:block; margin-top:12px; font-size:2rem; font-weight:500; }
    .mode { grid-column:1/-1; display:flex; justify-content:space-between; align-items:center; gap:20px; margin-top:8px; }
    .activity { margin-top:30px; } .activity h2 { font:500 1.5rem Georgia,serif; margin:0 0 14px; }
    .panels { display:grid; grid-template-columns:repeat(2,1fr); gap:14px; } .panel h3 { margin:0 0 12px; font-size:.9rem; }
    .item { border-top:1px solid #29332d; padding:10px 0; color:#b8c5bc; font-size:.82rem; line-height:1.45; } .item:first-of-type { border:0; }
    .buttons { display:flex; flex-wrap:wrap; gap:8px; } button { appearance:none; border:1px solid #385346; background:#17241d; color:#edf3ee; border-radius:999px; padding:10px 16px; cursor:pointer; }
    button:hover { background:#244332; } button[data-mode=SHUTDOWN] { border-color:#6b3a37; background:#2b1918; }
    footer { color:#69756e; margin-top:28px; font-size:.82rem; }
    @media(max-width:700px){ header,.mode{align-items:flex-start;flex-direction:column}.grid,.panels{grid-template-columns:1fr 1fr} }
  </style>
</head>
<body><main>
  <header><div><div class="eyebrow">Local operations</div><h1>Sage Operator</h1></div><div id="health">Connecting…</div></header>
  <section class="grid" id="counts"></section>
  <section class="card mode"><div><span>Runtime mode</span><strong id="mode">—</strong></div><div class="buttons">
    <button data-mode="NORMAL">Normal</button><button data-mode="ECO">Eco</button><button data-mode="SLEEP">Sleep</button><button data-mode="SHUTDOWN">Shutdown</button>
  </div></section>
  <section class="activity"><h2>Recent activity</h2><div class="panels" id="details"></div></section>
  <footer>Conversation stays in Telegram. This localhost panel controls and observes Sage only.</footer>
</main><script>
const labels={approvals:'Pending approvals',auditEvents:'Audit events',calendarEvents:'Calendar events',cases:'Active cases',documents:'Documents',driveFiles:'Drive files',emails:'Email messages',researchRuns:'Research runs',schedules:'Active schedules',tasks:'Open tasks'};
function escapeText(value){const element=document.createElement('span');element.textContent=value??'—';return element.innerHTML;}
function describe(item){return Object.entries(item).filter(([key])=>key!=='id').map(([key,value])=>`${escapeText(key)}: ${escapeText(value)}`).join('<br>');}
async function refresh(){try{const [overviewResponse,detailsResponse]=await Promise.all([fetch('/v1/operator/overview'),fetch('/v1/operator/details')]);if(!overviewResponse.ok||!detailsResponse.ok)throw new Error('status');const overview=await overviewResponse.json();const details=await detailsResponse.json();document.querySelector('#health').textContent='Core '+overview.status;document.querySelector('#mode').textContent=overview.mode;document.querySelector('#counts').innerHTML=Object.entries(overview.counts).map(([key,value])=>`<article class="card"><span>${labels[key]}</span><strong>${value}</strong></article>`).join('');document.querySelector('#details').innerHTML=Object.entries(details).map(([key,items])=>`<article class="card panel"><h3>${labels[key]}</h3>${items.length?items.map(item=>`<div class="item">${describe(item)}</div>`).join(''):'<div class="item">None</div>'}</article>`).join('');}catch(error){throw new Error('Operator refresh failed',{cause:error});}}
for(const button of document.querySelectorAll('button[data-mode]'))button.addEventListener('click',async()=>{try{const mode=button.dataset.mode;if(mode==='SHUTDOWN'&&!confirm('Stop all Sage services and Docker?'))return;const response=await fetch('/v1/operator/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});if(!response.ok)throw new Error('mode');await refresh();}catch(error){document.querySelector('#health').textContent='Mode change failed';}});
refresh().catch(()=>document.querySelector('#health').textContent='Core unavailable');setInterval(()=>refresh().catch(()=>{}),5000);
</script></body></html>"""
