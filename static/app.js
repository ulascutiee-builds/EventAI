function toggleSidebar(){document.querySelector('.sidebar')?.classList.toggle('open')}
function setQuestion(q){const el=document.getElementById('question');if(el){el.value=q;el.focus()}}
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(x=>x.classList.remove('active'));
    btn.classList.add('active'); document.getElementById('tab-'+btn.dataset.tab)?.classList.add('active')
  }));
  const canvas=document.getElementById('overviewChart');
  if(canvas){
    const data=JSON.parse(canvas.dataset.values||'{}'); const ctx=canvas.getContext('2d');
    function draw(){const ratio=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;canvas.width=w*ratio;canvas.height=h*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);
      const items=[['Đăng ký',data.registrations||0],['Check-in',data.checkins||0],['Phản hồi',data.feedbacks||0]],max=Math.max(1,...items.map(x=>x[1]));
      const top=28,bottom=40,left=48,right=20,ch=h-top-bottom,cw=w-left-right; ctx.font='11px Segoe UI';ctx.fillStyle='#94a3b8';
      for(let i=0;i<=4;i++){const y=top+ch*i/4;ctx.strokeStyle='#edf1f6';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillText(Math.round(max*(4-i)/4),8,y+4)}
      const slot=cw/items.length,bw=Math.min(70,slot*.45);items.forEach((it,i)=>{const bh=ch*it[1]/max,x=left+slot*i+(slot-bw)/2,y=top+ch-bh;const g=ctx.createLinearGradient(0,y,0,y+bh);g.addColorStop(0,'#7c3aed');g.addColorStop(1,'#4f46e5');ctx.fillStyle=g;roundRect(ctx,x,y,bw,bh,10);ctx.fill();ctx.fillStyle='#334155';ctx.textAlign='center';ctx.font='600 11px Segoe UI';ctx.fillText(it[0],x+bw/2,h-14);ctx.fillStyle='#4f46e5';ctx.font='700 12px Segoe UI';ctx.fillText(it[1],x+bw/2,Math.max(15,y-8));ctx.textAlign='left'})}
    function roundRect(ctx,x,y,w,h,r){r=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath()}
    draw(); window.addEventListener('resize',draw)
  }
});
