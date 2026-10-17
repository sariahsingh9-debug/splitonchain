document.addEventListener('DOMContentLoaded',()=>{
 document.getElementById('print-invoice')?.addEventListener('click',()=>window.print());
 const sheets=document.querySelectorAll('.sheet');
 function fit(){if(matchMedia('print').matches)return;const scale=Math.min(1,(document.documentElement.clientWidth-24)/1102);sheets.forEach(el=>el.style.zoom=scale);}
 fit();addEventListener('resize',fit);addEventListener('beforeprint',()=>sheets.forEach(el=>el.style.zoom=''));addEventListener('afterprint',fit);
});
