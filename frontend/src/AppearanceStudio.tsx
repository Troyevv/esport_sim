import { useState } from "react";
import { Tabs } from "./GameUI";
import { Avatar, LineupPortrait } from "./SceneIdentity";
import { GamePortrait } from "./GamePortrait";
import { entityVisual, teamKit, type Pack, type Entity, type Group } from "./databaseModel";
import { KitEditor, KitPreview } from "./KitStudio";
import PortraitCrop from "./PortraitCrop";
import PortraitEditor from "./PortraitEditor";
import { resolvePortrait } from "./portraits";
import "./appearance.css";

const tabs = ["Портреты игроков","Форма команд","Эмблемы","Личные пакеты"];
type Props = {
  pack:Pack; group:Group; id:string; record?:Entity; busy:boolean; latest:boolean; dirty:boolean;
  move:(group:Group,id:string)=>boolean; patch:(value:Partial<Entity>)=>void;
  save:()=>void; cancel:()=>void; library:React.ReactNode;
};

export default function AppearanceStudio({pack,group,id,record,busy,latest,dirty,move,patch,save,cancel,library}:Props) {
  const [tab,setTab]=useState(tabs[0]);
  const [query,setQuery]=useState("");
  const [limit,setLimit]=useState(32);
  const [background,setBackground]=useState("graphite");
  const [guides,setGuides]=useState(false);
  const nextTab=(value:string)=>{
    if(value===tab)return;
    const next=value===tabs[0]?"players":"teams";
    if(value!==tabs[3] && group!==next && !move(next,Object.keys(pack[next])[0] || ""))return;
    setTab(value);setQuery("");setLimit(32);
  };
  const catalog=group==="players"?pack.players:pack.teams;
  const rows=Object.entries(catalog).filter(([,r])=>(r.name+" "+(r.realName || "")).toLowerCase().includes(query.trim().toLowerCase())).sort((a,b)=>a[1].name.localeCompare(b[1].name));
  const v=record && catalog[id] ? entityVisual(pack,group,id):null;
  const currentKit=group==="teams" && record ? {...teamKit(pack,id),id,name:record.name,design:record.kit,badge:resolvePortrait(record.logo)?.image || v?.photo && resolvePortrait(v.photo)?.image}:v?.kit;
  const player=group==="players";
  const photo=resolvePortrait(record?.photo);
  return <main className="ap-module">
    <Tabs items={tabs} value={tab} change={nextTab}/>
    {tab===tabs[3] ? library : <>
      <label className="ap-player-compact">{player?"Игрок":"Команда"}<select value={id} onChange={e=>move(group,e.target.value)}>
        {Object.entries(catalog).map(([key,r])=><option key={key} value={key}>{r.name}</option>)}</select></label>
      <div className="ap-portrait-layout">
        <aside className="ap-people-panel"><h2>{tab}</h2>
          <label>{player?"Найти игрока":"Найти команду"}<input type="search" value={query} onChange={e=>{setQuery(e.target.value);setLimit(32)}}/></label>
          <div className="ap-people-list">{rows.slice(0,limit).map(([key,r])=><button className={id===key?"selected":""} key={key} aria-pressed={id===key} onClick={()=>move(group,key)}>
            <Avatar name={r.name} {...entityVisual(pack,group,key)}/><span><strong>{r.name}</strong><small>{player?r.realName:r.region}</small></span></button>)}
            {rows.length>limit && <button onClick={()=>setLimit(limit+32)}>Показать ещё</button>}
            {!rows.length && <p>Совпадений нет.</p>}</div></aside>
        {record && v && <section className="ap-portrait-work"><header className="ap-work-heading"><div><h2>{record.name}</h2>
          <span>{player?(v.kit?.name || "Свободный агент"):record.region}</span></div></header>
          <div className="ap-portrait-grid"><div className="ap-preview-column"><div className={"ap-portrait-stage ap-bg-"+background}>
            {player ? (dirty && record.appearance ? <GamePortrait name={record.name} head={record.appearance.image} kit={v.kit}/> : <LineupPortrait name={record.name} visual={v} id={id}/>)
              : tab===tabs[1]?<GamePortrait name={record.name} kit={currentKit}/>:<Avatar name={record.name} {...v} photo={record.logo || v.photo}/>}
            {guides && <div className="ap-crop-guides" aria-hidden><i/><i/><b/><b/></div>}
          </div><div className="ap-bg-picker">{[["graphite","Графит"],["light","Светлый"],["club","Клубный"],["transparent","Прозрачность"]].map(([bg,title])=>
            <button key={bg} aria-label={"Фон · "+title} aria-pressed={bg===background} className={"ap-swatch ap-bg-"+bg} onClick={()=>setBackground(bg)}>{bg===background?"✓":""}</button>)}</div>
            <label><input type="checkbox" checked={guides} onChange={e=>setGuides(e.target.checked)}/> Направляющие кадра</label></div>
            <div className="ap-portrait-controls"><fieldset disabled={busy || !latest}><legend>{player?"Слои портрета":tab}</legend>
              {player ? <><PortraitEditor layer value={record.appearance} change={p=>patch({appearance:resolvePortrait(p)})}/>
                <PortraitEditor playerSource value={record.photo} change={photo=>patch({photo})}/>
                {photo?.image && <PortraitCrop key={id} photo={photo} change={photo=>patch({photo})} disabled={busy || !latest}/>}</>
                : tab===tabs[1] ? <KitEditor team={record} id={id} patch={patch}/> : <PortraitEditor value={record.logo} change={logo=>patch({logo})}/>}
              <div className="db-actions"><button disabled={!dirty} className="btn primary" onClick={save}>Сохранить изменения</button>
                {dirty && <button onClick={cancel}>Отмена</button>}</div>
            </fieldset>{player && <KitPreview pack={pack} id={id} selected={v.kit?.id}/>}</div></div>
        </section>}
      </div></>}
  </main>;
}
