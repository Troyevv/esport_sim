import {useEffect, useRef, useState} from "react";
import type {PhotoAsset} from "./portraits";

export default function PortraitCrop({photo,change,disabled}:{photo:PhotoAsset;change:(photo:PhotoAsset)=>void;disabled:boolean}) {
  const [crop,setCrop] = useState({zoom:100,x:0,y:0,angle:0});
  const [aspect,setAspect] = useState("4:5");
  const [message,setMessage] = useState("");
  const [ready,setReady] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [image,setImage] = useState<HTMLImageElement | null>(null);
  useEffect(()=>{
    let active=true;
    setReady(false);setImage(null);setMessage("");
    const source=new Image();
    source.crossOrigin="anonymous";
    source.onload=()=>{if(active)setImage(source)};
    source.onerror=()=>{if(active)setMessage("Исходник недоступен для кадрирования. Выберите файл фотографии в редакторе слоёв.")};
    source.src=photo.image;
    return ()=>{active=false;source.onload=null;source.onerror=null};
  },[photo.image]);
  useEffect(()=>{
    const stage=canvas.current, ctx=stage?.getContext("2d");
    if(!image || !stage || !ctx)return;
    const w=stage.width,h=stage.height;
    const scale=Math.min(w/image.naturalWidth,h/image.naturalHeight)*crop.zoom/100;
    ctx.clearRect(0,0,w,h);ctx.save();
    ctx.translate(w*(.5+crop.x/100),h*(.5+crop.y/100));ctx.rotate(crop.angle*Math.PI/180);
    ctx.scale(scale,scale);ctx.drawImage(image,-image.naturalWidth/2,-image.naturalHeight/2);
    ctx.restore();setReady(true);
  },[image,crop,aspect]);
  const apply=()=>{
    if(!canvas.current || !ready)return;
    try {
      const data=canvas.current.toDataURL("image/png");
      if(data.length>1398100){setMessage("Кадр больше 1 МиБ. Уменьшите детализацию исходника.");return}
      change({...photo,image:data,changes:[photo.changes,"Кадрирование "+aspect].filter(Boolean).join(" · ").slice(0,240)});
      setCrop({zoom:100,x:0,y:0,angle:0});setMessage("");
    } catch {setMessage("Источник ограничивает обработку изображения. Загрузите оригинальный файл фотографии.")}
  };
  return <details className="studio-crop"><summary>Кадр и композиция</summary><fieldset disabled={disabled}>
    <label>Формат кадра<select value={aspect} onChange={e=>setAspect(e.target.value)}>
      <option value="4:5">Карточка · 4:5</option><option value="1:1">Профиль · 1:1</option><option value="6:7">Портрет · 6:7</option>
    </select></label>
    <canvas ref={canvas} width={480} height={aspect==="1:1"?480:aspect==="4:5"?600:560} aria-label="Предпросмотр кадрирования"/>
    {([["zoom","Масштаб",50,240],["x","По горизонтали",-60,60],["y","По вертикали",-60,60],["angle","Поворот",-45,45]] as const).map(([key,label,min,max])=><label key={key}>{label} · {crop[key]}{key==="angle"?"°":"%"}
      <input type="range" min={min} max={max} value={crop[key]} onChange={e=>setCrop({...crop,[key]:Number(e.target.value)})}/></label>)}
    <button disabled={!ready} onClick={apply}>Применить кадр к исходной фотографии</button>{message && <p role="status">{message}</p>}
  </fieldset></details>;
}
