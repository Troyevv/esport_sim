import { useEffect, useState } from "react";
import { readJSON } from "./tactics";

export default function MapSelect({ value, change }: { value: string; change: (map: string) => void }) {
  const [maps, setMaps] = useState([{id: "depo", name: "Депо"}]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    readJSON<typeof maps>("/api/maps").then(list => { if (active) setMaps(list); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  return <label>Карта<select value={value} onChange={e => change(e.target.value)}>
    {maps.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
  </select>{error && <span role="alert">{error}</span>}</label>;
}
