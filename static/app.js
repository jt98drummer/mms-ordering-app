/* MMS Material Ordering Hub - ONE cart for all three stores + icons.
   A line is {type:"card"|"doc"|"swag", ...}. Checkout posts the whole cart to
   /api/checkout, which splits fulfillment and applies the approval rules. */
const CART_KEY = "mms_cart_v3";
function cartGet(){ try{return JSON.parse(localStorage.getItem(CART_KEY))||[];}catch(e){return [];} }
function cartSave(c){ localStorage.setItem(CART_KEY, JSON.stringify(c)); renderCartBadge(); }
function cartAdd(item){ const c=cartGet(); c.push(item); cartSave(c); }
function cartCount(){ return cartGet().length; }          // line count, mixed units
function cartOfType(t){ return cartGet().filter(i=>i.type===t); }
function renderCartBadge(){
  document.querySelectorAll('[data-cart-count]').forEach(el=>{
    const n=cartCount(); el.textContent=n; el.style.display=n?'inline-flex':'none';
  });
}
/* Documents are keyed by id+qty: adding the same doc twice updates it. */
function cartAddDoc(id, title, qty, thumb, meta){
  const c=cartGet(); const ex=c.find(i=>i.type==='doc' && i.id===id);
  if(ex){ ex.qty=qty; ex.meta=meta; } else { c.push({type:'doc', id, title, qty, thumb, meta}); }
  cartSave(c);
}
/* One-time migration from the two old carts so nobody loses a basket. */
(function migrateCarts(){
  try{
    if(localStorage.getItem(CART_KEY)) return;
    const out=[];
    const oldSwag=JSON.parse(localStorage.getItem("mms_cart_v2")||"[]");
    oldSwag.forEach(i=>{ if(i && i.type==='swag') out.push(i); });
    const oldDocs=JSON.parse(localStorage.getItem("mms_doccart_v1")||"[]");
    oldDocs.forEach(i=>{ if(i && i.id) out.push({type:'doc', id:i.id, title:i.title, qty:i.qty, thumb:i.thumb, meta:i.meta}); });
    if(out.length) localStorage.setItem(CART_KEY, JSON.stringify(out));
  }catch(e){}
})();

function toast(msg){
  let t=document.getElementById('mms-toast');
  if(!t){t=document.createElement('div');t.id='mms-toast';
    t.style.cssText='position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#1e2d3b;color:#fff;font-weight:700;font-size:13.5px;padding:12px 20px;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.3);z-index:80;opacity:0;transition:.25s;font-family:Raleway,sans-serif';
    document.body.appendChild(t);}
  t.textContent=msg; t.style.opacity='1';
  clearTimeout(window._tt); window._tt=setTimeout(()=>t.style.opacity='0',1800);
}
const ICONS={
 shirt:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M8 3l-4 3 2 3 2-1v11h8V8l2 1 2-3-4-3-2 2h-4z"/></svg>',
 jacket:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M8 3l-4 3 2 3 2-1v11h8V8l2 1 2-3-4-3-2 2h-4z"/><line x1="12" y1="5" x2="12" y2="20"/></svg>',
 hoodie:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M8 3l-4 4 2 3 2-1v11h8V9l2 1 2-3-4-4"/><path d="M8 3c0 2 1.8 3 4 3s4-1 4-3"/></svg>',
 cap:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M4 15c0-5 3.6-8 8-8s8 3 8 8"/><path d="M12 7v8"/><path d="M20 15H4l-1 3h18z"/></svg>',
 cup:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M7 4h10l-1 16H8L7 4z"/><line x1="7.4" y1="9" x2="16.6" y2="9"/></svg>',
 bag:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M6 8h12l-1 12H7L6 8z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/></svg>',
 device:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><rect x="7" y="3" width="10" height="18" rx="2"/><line x1="10.5" y1="18" x2="13.5" y2="18"/></svg>',
 notebook:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><rect x="5" y="3" width="13" height="18" rx="2"/><line x1="9" y1="7" x2="14" y2="7"/><line x1="9" y1="11" x2="14" y2="11"/></svg>',
 tag:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M4 4h8l8 8-8 8-8-8V4z"/><circle cx="8" cy="8" r="1.4"/></svg>',
 doc:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/></svg>',
 card:'<svg viewBox="0 0 24 24" fill="none" stroke="#1e2d3b" stroke-width="1.6"><rect x="3" y="6" width="18" height="12" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="6" y1="14" x2="12" y2="14"/></svg>'
};
function icon(k){ return ICONS[k]||ICONS.tag; }
document.addEventListener('DOMContentLoaded', renderCartBadge);

/* ---- Spotlight carousel: auto-rotates every few seconds, pauses on hover ----
   mountSpotlight(rootId, slidesHTML[], {interval}) renders the track + dots and
   wires arrows, dots, and the timer. Used by the documents "Trending" band and
   the swag "Crew favorites" band. */
function mountSpotlight(rootId, slides, opts){
  const root=document.getElementById(rootId); if(!root||!slides.length) return;
  const o=Object.assign({interval:5000}, opts||{});
  root.querySelector('.spot-track').innerHTML = slides.join('');
  const dots=root.querySelector('.spot-dots');
  if(dots) dots.innerHTML = slides.map((_,i)=>'<i data-i="'+i+'"'+(i?'':' class="on"')+'></i>').join('');
  const track=root.querySelector('.spot-track');
  let i=0, timer=null;
  function go(n){ i=(n+slides.length)%slides.length;
    track.style.transform='translateX(-'+(i*100)+'%)';
    if(dots) dots.querySelectorAll('i').forEach((d,k)=>d.classList.toggle('on',k===i)); }
  function start(){ stop(); if(slides.length>1) timer=setInterval(()=>go(i+1), o.interval); }
  function stop(){ if(timer){ clearInterval(timer); timer=null; } }
  const prev=root.querySelector('.spot-prev'), next=root.querySelector('.spot-next');
  if(prev) prev.onclick=()=>{ go(i-1); start(); };
  if(next) next.onclick=()=>{ go(i+1); start(); };
  if(dots) dots.onclick=e=>{ const t=e.target.closest('i'); if(t){ go(+t.dataset.i); start(); } };
  root.addEventListener('mouseenter', stop);
  root.addEventListener('mouseleave', start);
  if(slides.length<2){ [prev,next].forEach(b=>{ if(b) b.style.display='none'; }); }
  go(0); start();
}
