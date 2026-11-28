export function Mark({mark='major',size=64}:{mark?:'major'|'contenders'|'eu14'|'blast';size?:number}){const art={
major:<><path fill="#f5d18b" d="M44 3a20 20 0 0 0-18 26c-11-2-17-13-8-22C25 0 38 0 44 3Z"/><path fill="#f5a47b" d="M40 8 57 37H36zm-5 10-2 19H19z"/><path fill="#55dcd2" d="m4 40 25 5 30-6-10 12-22 5L9 49zm5 14 18 5 21-5-7 7-15 3z"/></>,
contenders:<><path fill="#fac76d" d="M8 28 5 13l11 7 4-14 11 12 13-13 1 15 13-4-5 16-15 7H23z"/><path fill="#ee7867" d="m11 35 13 5 8 10 10-12 12-6-6 19-17 12-17-12z"/><path fill="#fff0d1" d="m25 26 7-6 7 6-7 7z"/></>,
eu14:<><path fill="#d3fa83" d="m5 45 3-21 14-14-4 17-7 14 11-8-5 15zm16 11 7-24-5 1 14-25 9-5-8 24 9-3-17 31z"/><path fill="#7bc1b5" d="m36 55 15-24 8-3-3 17-12 9z"/></>,
blast:<><path fill="#f778af" d="m7 14 13 7 12-17 7 18 19-6-10 17 12 8-20 2-4 17-10-16-21 2 12-15z"/><path fill="#271735" d="m22 33 13-13-4 11 10-2-15 16 5-13z"/></>
};return <svg className="cp-mark" viewBox="-5 -5 74 74" width={size} height={size} role="img" aria-label="Игровая эмблема турнира">{art[mark]||art.major}</svg>;}
