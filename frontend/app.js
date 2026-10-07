const objective = document.getElementById('objective');
const runButton = document.getElementById('run-button');
const approval = document.getElementById('approval');
let timer;

const icons = {planner:'✦', postgres:'▦', vector:'⌁', investigator:'◌', parallel_investigations:'⇄', approval:'♢', verifier:'✓', report:'≡'};
const labels = {planner:'Planner', postgres:'Account intelligence', vector:'Evidence retrieval', investigator:'Investigator', approval:'Human approval', verifier:'Verifier', report:'Report composer'};

function toast(message){const el=document.getElementById('toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2800)}
function timeLabel(iso){return new Date(iso).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}
function render(run){
  document.getElementById('run-title').textContent = run.status === 'complete' ? 'Report ready for review' : run.status === 'awaiting_approval' ? 'Approval needed to continue' : 'Executing your objective';
  document.getElementById('trace-id').textContent = run.id;
  document.getElementById('run-meta').innerHTML = `<span class="live-indicator"></span>${run.status.replace('_',' ')} · ${run.progress}%`;
  const grid = document.getElementById('workflow-grid');
  grid.innerHTML = run.nodes.map(n => `<div class="workflow-card ${n.status}"><div class="node-top"><div class="node-icon">${icons[n.id]||'•'}</div><span class="node-state">${n.status.toUpperCase()}</span></div><strong>${n.label}</strong><p>${n.detail || 'Waiting to start'}</p></div>`).join('');
  document.getElementById('activity-list').innerHTML = run.events.length ? run.events.slice().reverse().map(e => `<div class="activity-item"><time>${timeLabel(e.at)}</time><p><b>${e.agent}</b>${e.message}</p></div>`).join('') : '<div class="empty-state">Starting trace stream…</div>';
  document.getElementById('evidence-list').innerHTML = run.evidence.length ? run.evidence.map(e => `<div class="evidence-item"><div class="evidence-title"><span>${e.title}</span><span class="confidence">${Math.round(e.confidence*100)}%</span></div><div class="evidence-source">${e.source}</div><p class="evidence-excerpt">“${e.excerpt}”</p></div>`).join('') : '<div class="empty-state">Evidence will be attached when the verifier finishes.</div>';
  if(run.status === 'awaiting_approval') showApproval(run);
}
function showApproval(run){
  if(document.getElementById('approval-action')) return;
  const action = document.createElement('div'); action.id='approval-action'; action.className='approval-banner'; action.innerHTML=`<span>♢</span><div><strong>Human approval requested</strong><small>Cogniflow is ready to create customer-facing recommendations.</small></div><button id="approve-btn">Approve & continue</button>`;
  document.querySelector('.section-heading').after(action);
  document.getElementById('approve-btn').onclick=async()=>{await fetch(`/api/runs/${run.id}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:true,note:'Approved in Cogniflow console'})}); action.remove(); toast('Approval recorded. Workflow resumed.'); poll(run.id)};
}
async function poll(id){clearTimeout(timer);const response=await fetch(`/api/runs/${id}`);if(!response.ok)return;const run=await response.json();render(run);if(['queued','running','awaiting_approval'].includes(run.status))timer=setTimeout(()=>poll(id),700)}
runButton.onclick=async()=>{if(objective.value.trim().length<12){toast('Add a little more detail to the objective.');return}runButton.disabled=true;runButton.innerHTML='Starting… <span>↗</span>';const response=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({objective:objective.value,approval_mode:approval.checked?'required':'autonomous'})});const run=await response.json();toast('Run started. Planner is decomposing the objective.');poll(run.id);runButton.disabled=false;runButton.innerHTML='Start run <span>↗</span>'};
