'use strict';
document.documentElement.classList.add('js');
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const projects = [
 {title:'Sushiro Circle',category:'food',label:'FOOD FILM',description:'The details you can almost taste.',videos:[{id:'1228379763',hash:'605378a1b2',name:'Food story 01'},{id:'1228380583',hash:'c1209074fd',name:'Food story 02'}]},
 {title:'Dulingo Pro Studio',category:'studios',label:'BEHIND THE SCENES',description:'Inside a 1,500 m² world of food production.',videos:[{id:'1228384578',name:'Behind the scenes 01'},{id:'1228385596',name:'Behind the scenes 02'},{id:'1228384985',name:'Behind the scenes 03'}]},
 {title:'Kitchow',category:'studios',label:'KITCHEN STUDIO',description:'A fresh setting. A different food story.',videos:[{id:'1228414237',name:'Kitchen studio'},{id:'1228414026',name:'Brand styling'},{id:'1228409790',name:'Food content'}]},
 {title:'Coca-Cola',category:'events',label:'EVENT COVERAGE',description:'The energy. The people. The moment.',videos:[{id:'1228401737',name:'Event film'}]},
 {title:'ELTAREK',category:'events',label:'EVENT COVERAGE',description:'An event story, seen from the inside.',videos:[{id:'1228373177',name:'Event film'}]},
 {title:'Orange',category:'events',label:'EVENT COVERAGE',description:'Live moments, brought into focus.',videos:[{id:'1228402121',name:'Event film'}]},
 {title:'FORTHING',category:'events',label:'EVENT COVERAGE',description:'Movement and detail, captured on location.',videos:[{id:'1228391014',name:'Event film'}]},
 {title:'RODGE',category:'events',label:'EVENT COVERAGE',description:'A closer look at the experience.',videos:[{id:'1228402529',name:'Event film'}]},
 {title:'Waadi Food',category:'events',label:'EVENT COVERAGE',description:'Good food. Real moments. Shared stories.',videos:[{id:'1228456594',name:'Event film'}]}
];
let activeFilter = 'all', expanded = false, lastFocus = null;
function renderProjects() {
 const matching=projects.map((p,i)=>({...p,index:i})).filter(p=>activeFilter==='all'||p.category===activeFilter);
 const visible=activeFilter==='all'&&!expanded?matching.slice(0,4):matching;
 $('#project-grid').innerHTML=visible.map(p=>`<button class="project-card" type="button" data-project="${p.index}" aria-label="Watch ${p.title}, ${p.videos.length} video${p.videos.length>1?'s':''}"><div class="project-image${p.category==='studios'?' project-image-logo':''}"><img src="${p.category==='studios'?'assets/images/brand-'+(p.index===1?7:8)+'.webp':'assets/images/work-'+p.videos[0].id+'.webp'}" alt="${p.category==='studios'?p.title+' brand logo':'A still from '+p.title+' — '+p.label.toLowerCase()}" loading="lazy" width="1000" height="1000"><span class="project-number">${String(p.index+1).padStart(2,'0')} / SELECTED WORK</span><span class="project-play" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none"/></svg></span><span class="clip-count">${String(p.videos.length).padStart(2,'0')} FILM${p.videos.length>1?'S':''}</span><span class="project-arrow" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span></div><div class="project-meta"><div><h3>${p.title}</h3><p>${p.description}</p></div><span>${p.label}</span></div></button>`).join('');
 $('#more-work').hidden=activeFilter!=='all';
 $('#more-work').innerHTML=expanded?'Fewer stories <span><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 21V3m-7 7 7-7 7 7"/></svg></span>':'More stories <span><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 3v18m-7-7 7 7 7-7"/></svg></span>';
 $('#work-count').textContent=`SHOWING ${String(visible.length).padStart(2,'0')} / ${String(matching.length).padStart(2,'0')}`;
 $('#filter-status').textContent=`${visible.length} ${activeFilter==='all'?'':activeFilter+' '}projects shown`;
}
renderProjects();
$('.filters').addEventListener('click',e=>{
 const button=e.target.closest('[data-filter]');if(!button)return;
 activeFilter=button.dataset.filter;
 $$('.filters button').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
 renderProjects();
});
$('#more-work').addEventListener('click',()=>{expanded=!expanded;renderProjects();if(!expanded)$('#work').scrollIntoView({behavior:reduced.matches?'instant':'smooth'});});
const dialog=$('#video-dialog');
function selectClip(project,index){
 const video=project.videos[index];
 const src=`https://player.vimeo.com/video/${video.id}?${video.hash?'h='+video.hash+'&':''}dnt=1&title=0&byline=0&portrait=0&controls=1&autopause=1&playsinline=1`;
 const screen=$('#video-screen');screen.replaceChildren();
 const hint=document.createElement('span');hint.textContent='Loading film from Vimeo…';screen.appendChild(hint);
 const iframe=document.createElement('iframe');iframe.src=src;iframe.title=`${project.title} — ${video.name}`;iframe.allow='autoplay; fullscreen; picture-in-picture; encrypted-media';iframe.allowFullscreen=true;iframe.referrerPolicy='strict-origin-when-cross-origin';iframe.addEventListener('load',()=>hint.remove());screen.appendChild(iframe);
 $('#vimeo-direct').href=`https://vimeo.com/${video.id}${video.hash?'/'+video.hash:''}`;
 $$('#clip-tabs button').forEach((b,i)=>{b.classList.toggle('active',i===index);b.setAttribute('aria-pressed',String(i===index));});
}
function openProject(index){
 const project=projects[index];lastFocus=document.activeElement;
 $('#dialog-title').textContent=project.title;$('#dialog-category').textContent=project.label;
 $('#clip-tabs').replaceChildren();
 project.videos.forEach((video,i)=>{const b=document.createElement('button');b.type='button';b.textContent=video.name;b.addEventListener('click',()=>selectClip(project,i));$('#clip-tabs').appendChild(b);});
 dialog.showModal();selectClip(project,0);$('.dialog-close').focus();
}
$('#project-grid').addEventListener('click',e=>{const card=e.target.closest('[data-project]');if(card)openProject(Number(card.dataset.project));});
$('.dialog-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',e=>{if(e.target!==dialog)return;const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();});
dialog.addEventListener('close',()=>{$('#video-screen').replaceChildren();lastFocus?.focus();});
const menu=$('.menu-toggle'), mobile=$('#mobile-nav');
function closeMenu(){menu.setAttribute('aria-expanded','false');menu.setAttribute('aria-label','Open menu');mobile.hidden=true;}
menu.addEventListener('click',()=>{const opening=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(opening));menu.setAttribute('aria-label',opening?'Close menu':'Open menu');mobile.hidden=!opening;});
mobile.addEventListener('click',e=>{if(e.target.closest('a'))closeMenu();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeMenu();}});
const briefs={
 'Food film':'A closer look at your food. Filming, a social-first edit, and color finishing.',
 'Event coverage':'The energy of your event. On-location coverage and a short-form highlight story.',
 'BTS / Social':'The story behind the story. Candid filming and vertical edits made for Reels and Stories.'
};
$('.brief-choices').addEventListener('click',e=>{const b=e.target.closest('[data-brief]');if(!b)return;$$('.brief-choices button').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b));});$('#brief-project').value=b.dataset.brief;$('#brief-description').textContent=briefs[b.dataset.brief];});
$('#brief-form').addEventListener('submit',e=>{
 e.preventDefault();const form=e.currentTarget;if(!form.reportValidity())return;
 const d=new FormData(form),name=d.get('name').trim(),message=d.get('message').trim();
 if(!name||message.length<10){$('#form-status').textContent='Please add your name and at least 10 characters about your idea.';return;}
 const body=`Hi Mohamed,\n\nI'd like to discuss a ${d.get('project').toLowerCase()} project.\n\nName: ${name}\nEmail: ${d.get('email')}\n\n${message}\n\nThanks,\n${name}`;
 const href=`mailto:ffawziko@gmail.com?subject=${encodeURIComponent(d.get('project')+' project — '+name)}&body=${encodeURIComponent(body)}`;
 const a=document.createElement('a');a.href=href;document.body.appendChild(a);a.click();a.remove();
 $('#form-status').textContent='Your email draft is ready. Complete sending in your email app. If it didn’t open, email ffawziko@gmail.com or use WhatsApp.';
});
$('#year').textContent=new Date().getFullYear();
// Scroll motion uses an interpolated target, not an auto-playing loop.
// This is an animated still, not AI-generated camera-motion footage.
let target=0,current=0,raf=0,scrollTrigger=null;
function measure(){const t=$('.hero-track');target=Math.max(0,Math.min(1,-t.getBoundingClientRect().top/Math.max(1,t.offsetHeight-innerHeight)));requestTick();}
function requestTick(){if(!raf&&!reduced.matches)raf=requestAnimationFrame(tick);}
function tick(){
 raf=0;current+=(target-current)*.085;if(Math.abs(current-target)<.0003)current=target;
 const p=current, out=Math.max(0,Math.min(1,(p-.14)/.28)), second=Math.max(0,Math.min(1,(p-.46)/.3));
 const visual=$('.hero-visual picture');
 visual.style.transform=`translate3d(${p*-4}%,${p*1.8}%,0) scale(${1+p*.22}) rotate(${p*-1.7}deg) rotateY(${p*-4}deg)`;
 $('.hero-copy').style.opacity=String(1-out);
 $('.hero-copy').style.marginTop=`${-out*35}px`;
 $('.hero-copy').style.pointerEvents=out>.8?'none':'';
 $('.hero-copy').inert=out>.8;
 $('.hero-second').style.opacity=String(second);
 $('.hero-second').style.marginTop=`${(1-second)*20}px`;
 $('.hero-progress i').style.transform=`scaleX(${p})`;
 $('.hero-time').innerHTML=`${p<.35?'01':p<.7?'02':'03'} <span>/</span> 03`;
 if(current!==target)requestTick();
}
function initMotion(){
 if(reduced.matches)return;
 if(window.gsap&&window.ScrollTrigger){
  gsap.registerPlugin(ScrollTrigger);
  scrollTrigger=ScrollTrigger.create({trigger:'.hero-track',start:'top top',end:'bottom bottom',onUpdate:self=>{target=self.progress;requestTick();}});
  gsap.utils.toArray('.reveal').forEach(el=>gsap.fromTo(el,{y:30,opacity:.3},{y:0,opacity:1,duration:1,ease:'power2.out',scrollTrigger:{trigger:el,start:'top 90%',once:true}}));
 }else{window.addEventListener('scroll',measure,{passive:true});window.addEventListener('resize',measure,{passive:true});measure();}
}
initMotion();
reduced.addEventListener('change',()=>{scrollTrigger?.kill();cancelAnimationFrame(raf);raf=0;current=target=0;$('.hero-visual picture').style.transform='';$('.hero-copy').style.opacity='';$('.hero-copy').style.marginTop='';$('.hero-copy').style.pointerEvents='';$('.hero-copy').inert=false;$('.hero-second').style.opacity='0';if(!reduced.matches)initMotion();});
const finishLoading=()=>$('.loader').classList.add('loaded');
Promise.all([document.fonts.ready,$('#hero-image').decode().catch(()=>{})]).then(()=>setTimeout(finishLoading,250));
setTimeout(finishLoading,2200);
// Local dependencies are bundled. If unavailable on a hosted deployment, retry via CDN.
if(!window.gsap||!window.ScrollTrigger){
 const loadScript=src=>new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=src;s.onload=resolve;s.onerror=reject;document.head.appendChild(s);});
 (async()=>{try{if(!window.gsap)await loadScript('https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js');if(!window.ScrollTrigger)await loadScript('https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js');window.removeEventListener('scroll',measure);window.removeEventListener('resize',measure);initMotion();}catch(e){/* Native scroll fallback stays active. */}})();
}
