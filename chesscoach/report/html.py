"""Bilan visuel par partie : HTML autonome avec navigation coup par coup (JS minimal, aucune dépendance
réseau), barre et courbe d'éval, flèches joué/meilleur, moments critiques et explications vérifiées.
``python -m chesscoach.report.html --username Kuga06 --games 10 --out reports/html``"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from pathlib import Path

import chess
import chess.svg

from chesscoach import db
from chesscoach.agents.critic import abstention
from chesscoach.agents.facts import build_facts
from chesscoach.engine.analyse import load_evals
from chesscoach.engine.analysis import move_losses
from chesscoach.report.render import TAG_LABEL

SEV_FR = {"blunder": "Gaffe", "mistake": "Erreur", "inaccuracy": "Imprécision"}

CSS = """
:root{--bg:#141412;--panel:#1f1e1b;--panel2:#292825;--line:#34332f;--text:#ecebe6;--muted:#9c9a92;
--green:#7fc97f;--red:#e5533d;--orange:#e89b3c;--yellow:#e6c84a;--blue:#7fb3e5;--light:#eeeed2;--dark:#769656;--radius:14px}
*{box-sizing:border-box}html{color-scheme:dark}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 -apple-system,system-ui,"Segoe UI",Inter,Roboto,sans-serif;padding:16px}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1040px;margin:0 auto}.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px}
h1{font-size:1.35rem;margin:0;font-weight:650;letter-spacing:-.01em}h2{font-size:1.05rem;margin:28px 0 12px;font-weight:650;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.meta{color:var(--muted);font-size:.9rem;display:flex;gap:14px;flex-wrap:wrap}.meta b{color:var(--text);font-weight:600}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px}
.viewer{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;margin-top:12px}
@media(max-width:760px){.viewer{grid-template-columns:1fr}}
.boardwrap{display:flex;gap:10px;align-items:stretch}.evalbar{width:20px;border-radius:7px;background:#333;overflow:hidden;position:relative;flex:none}
.evalbar i{position:absolute;left:0;right:0;bottom:0;background:#f4f4f0;transition:height .25s}.evalbar b{position:absolute;left:0;right:0;text-align:center;font-size:9px;font-weight:700;line-height:1;padding:3px 0}
svg.board{width:100%;height:auto;max-width:520px;border-radius:8px;display:block;flex:1}
.ctrl{display:flex;gap:8px;margin-top:10px;align-items:center}.ctrl button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:8px 14px;font-size:1rem;cursor:pointer}
.ctrl button:hover{background:#33322e}.btn{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:6px 12px;cursor:pointer}svg.board{touch-action:none}.pc{cursor:grab}.ctrl .pos{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums}
.side{display:flex;flex-direction:column;gap:12px;min-width:0}
.now{padding:14px}.now .mv{font-size:1.5rem;font-weight:700}.now .ev{font-variant-numeric:tabular-nums;color:var(--muted)}
.chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.8rem;font-weight:650;background:var(--panel2);color:var(--text);margin:2px 6px 2px 0}
.chip.blunder{background:var(--red);color:#fff}.chip.mistake{background:var(--orange);color:#1a1a1a}.chip.inaccuracy{background:var(--yellow);color:#1a1a1a}
.chip.best{background:var(--green);color:#10250f}.chip.tag{background:#3a3a55;color:#dfe0ff}
.moves{padding:10px 12px;max-height:340px;overflow:auto;font-variant-numeric:tabular-nums;line-height:1.9}
.moves .n{color:var(--muted);display:inline-block;width:2.4em}.moves span.m{padding:1px 6px;border-radius:6px;cursor:pointer;display:inline-block;min-width:3.6em}
.moves span.m:hover{background:var(--panel2)}.moves span.m.cur{background:#3d3c37;outline:1px solid #57564f}
.moves span.m.blunder{color:var(--red);font-weight:700}.moves span.m.mistake{color:var(--orange)}.moves span.m.inaccuracy{color:var(--yellow)}
.curvewrap{position:relative}.curve{width:100%;height:110px;display:block;border-radius:10px;background:#111}.dot{position:absolute;width:11px;height:11px;border-radius:50%;border:2px solid #111;transform:translate(-50%,-50%);cursor:pointer}.dot.cur{width:15px;height:15px;border-color:#fff}
.summary{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:10px;color:var(--muted);font-size:.9rem}
.summary .k{display:flex;align-items:center;gap:6px}.summary i{width:10px;height:10px;border-radius:50%;display:inline-block}
.moment{display:grid;grid-template-columns:200px minmax(0,1fr);gap:16px;padding:14px;margin-bottom:12px;cursor:pointer;transition:border-color .15s}
.moment:hover{border-color:#57564f}@media(max-width:560px){.moment{grid-template-columns:1fr}}
.moment svg{width:100%;height:auto;border-radius:6px}.moment .h{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.moment .h .mv{font-size:1.15rem;font-weight:700}
.moment .ev{color:var(--muted);font-variant-numeric:tabular-nums}.moment p{margin:8px 0 0}.moment details{margin-top:8px;color:var(--muted);font-size:.88rem}
.moment summary{cursor:pointer}.legend{color:var(--muted);font-size:.85rem;margin-top:8px}.legend i{display:inline-block;width:14px;height:4px;border-radius:2px;vertical-align:middle;margin:0 4px 0 10px}
table.idx{width:100%;border-collapse:collapse}table.idx th{text-align:left;color:var(--muted);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;border-bottom:1px solid var(--line)}
table.idx td{padding:10px;border-bottom:1px solid var(--line)}table.idx tr:hover td{background:var(--panel2)}.win{color:var(--green)}.loss{color:var(--red)}.draw{color:var(--muted)}
.dots i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:3px}
"""

JS = """
const D=window.__DATA__;const L=D.plies;let i=D.start||0;let flip=D.flip;let trial=null;let sel=null;let timer=null;const form={};let saved=null;
const $=q=>document.querySelector(q);const svg=$('svg.board');
function sq(f,r){return flip?[7-f,7-r]:[f,r]}
function uciSq(u){return [u.charCodeAt(0)-97,+u[1]-1]}
function parseFen(fen){const rows=fen.split(' ')[0].split('/');const b={};for(let r=0;r<8;r++){let f=0;for(const c of rows[r]){if(/\\d/.test(c)){f+=+c;continue}b[f+','+(7-r)]=c;f++}}return b}
function toFen(b,turn){let rows=[];for(let r=7;r>=0;r--){let s='',e=0;for(let f=0;f<8;f++){const c=b[f+','+r];if(c){if(e){s+=e;e=0}s+=c}else e++}if(e)s+=e;rows.push(s)}return rows.join('/')+' '+turn}
function applyMove(fen,code){const b=parseFen(fen);const turn=fen.split(' ')[1];const [f1,r1]=uciSq(code.slice(0,2)),[f2,r2]=uciSq(code.slice(2,4));const kind=code[code.length-1];
let pc=b[f1+','+r1];delete b[f1+','+r1];
if(kind==='e'){delete b[f2+','+r1]}
if(kind==='c'){const rookF=f2>f1?7:0,rookT=f2>f1?5:3;const rk=b[rookF+','+r1];delete b[rookF+','+r1];b[rookT+','+r1]=rk}
if(kind==='p'){const promo=code[4];pc=turn==='w'?promo.toUpperCase():promo}
b[f2+','+r2]=pc;return toFen(b,turn==='w'?'b':'w')}
function curFen(){return trial?trial.fen:L[i].fen}
function renderBoard(fen,extra){const b=parseFen(fen);let s='';
for(let r=0;r<8;r++)for(let f=0;f<8;f++){const [x,y]=sq(f,r);s+=`<rect class="sqr" x="${x*45}" y="${(7-y)*45}" width="45" height="45" fill="${(f+r)%2?'#eeeed2':'#769656'}"/>`}
for(const h of (extra.hl||[])){const [x,y]=sq(h[0],h[1]);s+=`<rect x="${x*45}" y="${(7-y)*45}" width="45" height="45" fill="${h[2]}" opacity=".55" pointer-events="none"/>`}
for(const k in b){const [f,r]=k.split(',').map(Number);const [x,y]=sq(f,r);const c=b[k];const id=(c===c.toUpperCase()?'w':'b')+c.toLowerCase();
s+=`<use class="pc" data-f="${f}" data-r="${r}" href="#${id}" x="${x*45}" y="${(7-y)*45}" width="45" height="45"/>`}
for(const t of (extra.dots||[])){const [x,y]=sq(t[0],t[1]);s+=t[2]?`<circle cx="${x*45+22.5}" cy="${(7-y)*45+22.5}" r="20" fill="none" stroke="rgba(0,0,0,.25)" stroke-width="5" pointer-events="none"/>`:`<circle cx="${x*45+22.5}" cy="${(7-y)*45+22.5}" r="7" fill="rgba(0,0,0,.25)" pointer-events="none"/>`}
for(const a of (extra.arrows||[])){const [x1,y1]=sq(a[0],a[1]),[x2,y2]=sq(a[2],a[3]);s+=`<line x1="${x1*45+22.5}" y1="${(7-y1)*45+22.5}" x2="${x2*45+22.5}" y2="${(7-y2)*45+22.5}" stroke="${a[4]}" stroke-width="9" stroke-linecap="round" opacity=".85" marker-end="url(#ah-${a[5]})" pointer-events="none"/>`}
for(let f=0;f<8;f++){const [x]=sq(f,0);s+=`<text x="${x*45+38}" y="${8*45-3}" font-size="10" fill="${(flip?f:f+1)%2?'#eeeed2':'#769656'}" pointer-events="none">${'abcdefgh'[f]}</text>`}
for(let r=0;r<8;r++){const [,y]=sq(0,r);s+=`<text x="2" y="${(7-y)*45+11}" font-size="10" fill="${(flip?r+1:r)%2?'#eeeed2':'#769656'}" pointer-events="none">${r+1}</text>`}
return s}
function legalFrom(f,r){const from='abcdefgh'[f]+(r+1);return (L[i].legal||[]).filter(c=>c.startsWith(from))}
function show(){const p=L[i];const cm=D.momentsByPly[i+1];const extra={hl:[],arrows:[],dots:[]};
if(trial){extra.hl.push([...uciSq(trial.code.slice(0,2)),'#9bd3f5'],[...uciSq(trial.code.slice(2,4)),'#9bd3f5'])}
else if(i>0&&L[i].uci){const m=L[i].uci;extra.hl.push([...uciSq(m.slice(0,2)),'#f6f669'],[...uciSq(m.slice(2,4)),'#f6f669'])}
if(sel){extra.hl.push([sel[0],sel[1],'#f6f669']);const b=parseFen(curFen());for(const c of legalFrom(sel[0],sel[1])){const t=uciSq(c.slice(2,4));extra.dots.push([t[0],t[1],!!b[t[0]+','+t[1]]])}}
if(cm&&(trial||D.reveal[i+1])){const pl=uciSq(cm.played_uci.slice(0,2)),pl2=uciSq(cm.played_uci.slice(2,4)),b1=uciSq(cm.best_uci.slice(0,2)),b2=uciSq(cm.best_uci.slice(2,4));
extra.arrows.push([...pl,...pl2,'#e5533d','red'],[...b1,...b2,'#3ca63c','green'])}
$('#bsq').innerHTML=renderBoard(curFen(),extra);
const cp=p.cp;const pct=Math.max(4,Math.min(96,50+(D.userWhite?cp:-cp)/1000*50*0.9));const bar=$('.evalbar');
bar.querySelector('i').style.height=pct+'%';const lab=bar.querySelector('b');lab.textContent=p.label;lab.style.top=pct>50?'':'auto';lab.style.bottom=pct>50?'0':'';lab.style.color=pct>50?'#111':'#eee';
const now=$('#now');const turnTxt=p.fen.split(' ')[1]==='w'?'trait aux blancs':'trait aux noirs';
if(cm&&!D.reveal[i+1]&&!trial){const nm=L[i+1];const f=form[i]||(form[i]={plan:'',conf:50});
now.innerHTML=`<div class="ev" style="text-transform:uppercase;letter-spacing:.06em;font-size:.75rem">Moment critique · ${turnTxt}</div><div class="mv">À toi de jouer</div><p style="margin:8px 0 0;color:var(--muted)">Coup ${nm.num} : note ton plan et ta confiance, puis joue ton coup sur l'échiquier.</p>
<textarea id="plan" rows="2" placeholder="Ton plan en une phrase (facultatif)" style="width:100%;margin-top:8px;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit">${f.plan}</textarea>
<label style="display:flex;align-items:center;gap:10px;margin-top:8px;color:var(--muted)">Confiance <input id="conf" type="range" min="0" max="100" value="${f.conf}" style="flex:1"><b id="confv" style="color:var(--text);width:3ch">${f.conf}</b></label>
<div style="margin-top:10px"><button class="btn" id="reveal">Voir le verdict sans jouer</button>${D.served?'':'<span class="ev" style="margin-left:8px">(réponses non enregistrées : page hors serveur)</span>'}</div>`;
$('#plan').oninput=e=>{f.plan=e.target.value};$('#conf').oninput=e=>{f.conf=+e.target.value;$('#confv').textContent=e.target.value};
$('#reveal').onclick=()=>{D.reveal[i+1]=true;show()}}
else if(cm){const nm=L[i+1];let head='';
if(trial){const same=c=>c.slice(0,4)===trial.code.slice(0,4);
if(same(cm.best_uci))head=`<div class="mv" style="color:var(--green)">✔ ${trial.san} — c'est le meilleur coup</div><div class="ev">Stockfish : ${p.label} maintenu</div>`;
else if(same(cm.played_uci))head=`<div class="mv" style="color:var(--red)">${trial.san} — c'est le coup joué en partie</div><div class="ev">${p.label} → ${nm.label} · perte ${nm.loss} cp</div>`;
else head=`<div class="mv" style="color:var(--blue)">${trial.san} — coup légal, non évalué</div><div class="ev">Seuls le coup joué et le meilleur coup ont une éval moteur ici ; je ne juge pas ce coup.</div>`}
else head=`<div class="mv">${nm.num}${nm.dots}${nm.san} <span style="color:var(--red);font-size:1rem">joué</span></div><div class="ev">${p.label} → ${nm.label} · perte ${nm.loss} cp</div>`;
now.innerHTML=`<div class="ev" style="text-transform:uppercase;letter-spacing:.06em;font-size:.75rem">Moment critique · ${turnTxt}${saved?' · <span id="saved">'+saved+'</span>':''}</div>${head}<div style="margin-top:6px"><span class="chip ${nm.sev}">${nm.sevfr}</span><span class="chip tag">${nm.tag}</span><span class="chip best">meilleur : ${cm.best_san}</span></div><p style="margin:10px 0 0;color:var(--muted);font-size:.92rem">${cm.text}</p>`}
else if(trial){now.innerHTML=`<div class="mv" style="color:var(--blue)">${trial.san} <span style="font-size:1rem">essai</span></div><div class="ev">Coup légal. Pas d'évaluation moteur pour les variantes dans ce bilan.</div>`}
else if(i===0){now.innerHTML='<div class="mv">Position initiale</div><div class="ev">Éval '+p.label+'</div>'}
else{const m=L[i-1];now.innerHTML=`<div class="mv">${m.num}${m.dots}${m.san}</div><div class="ev">${L[i-1].label} → ${p.label}${m.mine&&m.loss>=50?' · perte '+m.loss+' cp':''}</div><div style="margin-top:6px">${m.sev?`<span class="chip ${m.sev}">${m.sevfr}</span>`:''}${m.tag?`<span class="chip tag">${m.tag}</span>`:''}</div>`}
$('#undo').hidden=!trial;
document.querySelectorAll('.moves span.m').forEach(e=>e.classList.toggle('cur',+e.dataset.i===i));
const cur=$('.moves span.m.cur');if(cur)cur.scrollIntoView({block:'nearest'});
$('#pos').textContent=i+' / '+(L.length-1);
document.querySelectorAll('.dot').forEach(c=>c.classList.toggle('cur',+c.dataset.i===i))}
function go(n){i=Math.max(0,Math.min(L.length-1,n));trial=null;sel=null;show()}
function sanOf(code){const b=parseFen(L[i].fen);const pc=b[uciSq(code.slice(0,2)).join(',')]||'';const cap=!!b[uciSq(code.slice(2,4)).join(',')]||code.endsWith('e');const k=code[code.length-1];
if(k==='c')return code[2]==='g'?'O-O':'O-O-O';const P=pc.toUpperCase()==='P'?(cap?code[0]:''):pc.toUpperCase();return P+(cap?'x':'')+code.slice(2,4)+(k==='p'?'='+code[4].toUpperCase():'')}
function tryMove(f1,r1,f2,r2){const from='abcdefgh'[f1]+(r1+1),to='abcdefgh'[f2]+(r2+1);let codes=(L[i].legal||[]).filter(c=>c.startsWith(from+to));if(!codes.length)return false;
let code=codes.find(c=>c[4]==='q')||codes[0];trial={code,fen:applyMove(L[i].fen,code),san:sanOf(code)};sel=null;
const cm=D.momentsByPly[i+1];if(cm&&D.served&&!D.reveal[i+1]){const same=c=>c.slice(0,4)===code.slice(0,4);const verdict=same(cm.best_uci)?'best':same(cm.played_uci)?'played':'other';const f=form[i]||{plan:'',conf:50};saved='…';
fetch('/api/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({game_number:D.gameNumber,ply:i+1,san:trial.san,plan:f.plan,confidence:f.conf,verdict})}).then(r=>r.json()).then(j=>{saved=j.ok?'enregistré ✓':'erreur : '+j.error;show()}).catch(()=>{saved='serveur injoignable';show()})}
else saved=null;show();return true}
let drag=null;
function squareAt(ev){const pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());const x=Math.floor(p.x/45),y=7-Math.floor(p.y/45);if(x<0||x>7||y<0||y>7)return null;return flip?[7-x,7-y]:[x,y]}
svg.addEventListener('pointerdown',ev=>{if(trial)return;const s=squareAt(ev);if(!s)return;const b=parseFen(L[i].fen);const pc=b[s.join(',')];const turn=L[i].fen.split(' ')[1];
if(sel&&tryMove(sel[0],sel[1],s[0],s[1]))return;
if(pc&&((turn==='w')===(pc===pc.toUpperCase()))&&legalFrom(s[0],s[1]).length){sel=s;show();const el=[...svg.querySelectorAll('.pc')].find(e=>+e.dataset.f===s[0]&&+e.dataset.r===s[1]);drag={from:s,el};svg.setPointerCapture(ev.pointerId)}else{sel=null;show()}});
svg.addEventListener('pointermove',ev=>{if(!drag||!drag.el)return;const pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());drag.el.setAttribute('x',p.x-22.5);drag.el.setAttribute('y',p.y-22.5);drag.el.style.pointerEvents='none';drag.moved=true});
svg.addEventListener('pointerup',ev=>{if(!drag)return;const s=squareAt(ev);const d=drag;drag=null;if(s&&d.moved&&!(s[0]===d.from[0]&&s[1]===d.from[1])){if(!tryMove(d.from[0],d.from[1],s[0],s[1])){sel=null;show()}}else if(d.moved){show()}});
$('#undo').onclick=()=>{trial=null;show()};$('#flip').onclick=()=>{flip=!flip;show()};
$('#auto').onclick=()=>{if(timer){clearInterval(timer);timer=null;$('#auto').textContent='▶▶';return}$('#auto').textContent='⏸';timer=setInterval(()=>{if(i>=L.length-1){clearInterval(timer);timer=null;$('#auto').textContent='▶▶';return}go(i+1)},900)};
document.addEventListener('keydown',e=>{if(e.key==='ArrowLeft')go(i-1);if(e.key==='ArrowRight')go(i+1);if(e.key==='Home')go(0);if(e.key==='End')go(L.length-1);if(e.key==='Escape'){trial=null;sel=null;show()}});
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>{const v=b.dataset.go;go(v==='+'?i+1:v==='-'?i-1:v==='0'?0:v==='$'?L.length-1:+v)}));
document.querySelectorAll('.moves span.m,.dot,.moment').forEach(e=>e.addEventListener('click',()=>{go(+e.dataset.i);if(e.classList.contains('moment'))window.scrollTo({top:0,behavior:'smooth'})}));
show();
"""


def piece_symbols() -> str:
    """Les 12 pièces SVG de python-chess, une seule fois, réutilisées par <use>."""
    out = []
    for color in (chess.WHITE, chess.BLACK):
        for pt in chess.PIECE_TYPES:
            svg = chess.svg.piece(chess.Piece(pt, color))
            inner = svg[svg.index(">") + 1 : svg.rindex("</svg>")]
            pid = ("w" if color else "b") + chess.piece_symbol(pt)
            out.append(f'<symbol id="{pid}" viewBox="0 0 45 45">{inner}</symbol>')
    arrows = "".join(
        f'<marker id="ah-{n}" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="2.2" markerHeight="2.2" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
        for n, c in (("red", "#e5533d"), ("green", "#3ca63c"))
    )
    return f'<svg width="0" height="0" style="position:absolute"><defs>{"".join(out)}{arrows}</defs></svg>'


def legal_moves(board: chess.Board) -> list[str]:
    """Coups légaux encodés « uci + type » : n normal, c roque, e prise en passant, p promotion (python-chess,
    jamais recalculé en JS)."""
    out = []
    for m in board.legal_moves:
        kind = "c" if board.is_castling(m) else "e" if board.is_en_passant(m) else "p" if m.promotion else "n"
        out.append(m.uci() + kind)
    return out


def eval_label(e) -> str:
    if e.terminal_winner is not None:
        return "1-0" if e.terminal_winner else "0-1"
    if e.mate_in is not None:
        return f"M{abs(e.mate_in)}"
    return f"{e.score_cp / 100:+.1f}"


def curve_svg(plies: list[dict], moments: dict[int, dict], user_white: bool) -> str:
    n = len(plies)
    xs = [i / max(1, n - 1) * 100 for i in range(n)]
    ys = []
    for p in plies:
        cp = p["cp"] if user_white else -p["cp"]
        ys.append(50 - max(-50, min(50, cp / 1000 * 50)))
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))
    area = f"0,50 {pts} 100,50"
    dots = "".join(
        f'<span class="dot" data-i="{ply - 1}" style="left:{xs[ply]:.2f}%;top:{ys[ply]:.2f}%;background:{SEV_COLOR[m["severity"]]}"></span>'
        for ply, m in moments.items()
        if ply < n
    )
    return (
        f'<div class="curvewrap"><svg class="curve" viewBox="0 0 100 100" preserveAspectRatio="none">'
        f'<defs><clipPath id="up"><rect x="0" y="0" width="100" height="50"/></clipPath><clipPath id="dn"><rect x="0" y="50" width="100" height="50"/></clipPath></defs>'
        f'<polygon points="{area}" fill="#eeeed2" opacity=".9" clip-path="url(#up)"/>'
        f'<polygon points="{area}" fill="#3b3a36" clip-path="url(#dn)"/>'
        f'<line x1="0" y1="50" x2="100" y2="50" stroke="#666" stroke-width=".4"/>'
        f'<polyline points="{pts}" fill="none" stroke="#7fc97f" stroke-width=".9" vector-effect="non-scaling-stroke"/></svg>{dots}</div>'
    )


SEV_COLOR = {"blunder": "#e5533d", "mistake": "#e89b3c", "inaccuracy": "#e6c84a"}


def static_board(fen: str, played: chess.Move, best: chess.Move, flip: bool) -> str:
    return chess.svg.board(
        chess.Board(fen),
        size=200,
        coordinates=False,
        orientation=chess.BLACK if flip else chess.WHITE,
        arrows=[
            chess.svg.Arrow(played.from_square, played.to_square, color="#e5533d"),
            chess.svg.Arrow(best.from_square, best.to_square, color="#3ca63c"),
        ],
        colors={"square light": "#eeeed2", "square dark": "#769656"},
    )


def game_page(conn: sqlite3.Connection, game: sqlite3.Row, served: bool = False) -> str:
    evals = load_evals(conn, game["id"])
    rows = conn.execute("SELECT san, clock_seconds FROM moves WHERE game_id = ? ORDER BY ply", (game["id"],)).fetchall()
    sans = [r["san"] for r in rows]
    losses = move_losses(evals, sans)
    user_white = game["user_color"] == "white"
    cms = {
        r["ply"]: r
        for r in conn.execute("SELECT * FROM critical_moments WHERE game_id = ? ORDER BY ply", (game["id"],))
    }
    board = chess.Board(evals[0].fen)
    plies = [
        {
            "fen": evals[0].fen,
            "cp": evals[0].to_cp(),
            "label": eval_label(evals[0]),
            "uci": None,
            "legal": legal_moves(board),
        }
    ]
    for k, san in enumerate(sans):
        mv = board.parse_san(san)
        ml = losses[k]
        board.push(mv)
        e = evals[k + 1]
        mine = ml.color == game["user_color"]
        plies.append(
            {
                "fen": e.fen,
                "cp": e.to_cp(),
                "label": eval_label(e),
                "uci": mv.uci(),
                "legal": legal_moves(board),
                "san": san,
                "num": (k + 2) // 2,
                "dots": "." if k % 2 == 0 else "…",
                "mine": mine,
                "loss": ml.loss,
                "sev": ml.severity if mine else None,
                "sevfr": SEV_FR.get(ml.severity or "", ""),
                "tag": TAG_LABEL[cms[k + 1]["primary_tag"]] if (k + 1) in cms else None,
            }
        )
    moments_js, cards = {}, []
    for ply, cm in cms.items():
        mf = build_facts(conn, game["id"], ply)
        b = chess.Board(cm["fen_before"])
        played, best = b.parse_san(cm["san"]), chess.Move.from_uci(cm["best_move"])
        text = abstention(mf)
        moments_js[ply] = {
            "played_uci": played.uci(),
            "best_uci": best.uci(),
            "best_san": mf.best_san,
            "text": html.escape(text),
        }
        num, dots = (ply + 1) // 2, "." if ply % 2 else "…"
        cards.append(
            f'<div class="card moment" data-i="{ply - 1}">'
            f"<div>{static_board(cm['fen_before'], played, best, not user_white)}</div><div>"
            f'<div class="h"><span class="mv">{num}{dots}{cm["san"]}</span><span class="chip {cm["severity"]}">{SEV_FR[cm["severity"]]}</span>'
            f'<span class="chip tag">{TAG_LABEL[cm["primary_tag"]]}</span>'
            + (f'<span class="chip">{int(cm["clock_seconds"])} s</span>' if cm["clock_seconds"] else "")
            + f'</div><div class="ev">{cm["before_cp"] / 100:+.2f} → {cm["after_cp"] / 100:+.2f} · meilleur <b style="color:var(--green)">{html.escape(mf.best_san)}</b></div>'
            f"<p>{html.escape(text)}</p><details><summary>faits vérifiés ({len(mf.facts)})</summary><ul>"
            + "".join(f"<li>{html.escape(f.text)}</li>" for f in mf.facts)
            + "</ul></details></div></div>"
        )
    mine_losses = [m for m in losses if m.color == game["user_color"]]
    sev = {s: sum(1 for m in mine_losses if m.severity == s) for s in SEV_FR}
    avg = sum(m.loss for m in mine_losses) / max(1, len(mine_losses))
    moves_html = []
    for k, p in enumerate(plies[1:], start=1):
        if k % 2 == 1:
            moves_html.append(f'<span class="n">{p["num"]}.</span>')
        moves_html.append(f'<span class="m {p["sev"] or ""}" data-i="{k}">{p["san"]}</span>')
    opp = game["black"] if user_white else game["white"]
    data = {
        "plies": plies,
        "momentsByPly": moments_js,
        "userWhite": user_white,
        "flip": not user_white,
        "start": min(cms) - 1 if cms else 0,
        "reveal": {},
        "served": served,
        "gameNumber": game["game_number"],
    }
    return f"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Partie n° {game["game_number"]} — ChessCoach</title><style>{CSS}</style><body><div class="wrap">{piece_symbols()}
<div class="top"><h1>Partie n° {game["game_number"]} · {"Blancs" if user_white else "Noirs"} contre {html.escape(opp)}</h1><a href="{"/" if served else "index.html"}">← toutes les parties</a></div>
<div class="meta"><span>{game["played_at"][:10]}</span><span>{game["time_class"]} {game["time_control"]}</span><span>Résultat : <b class="{game["user_result"]}">{game["user_result"]}</b></span><span><a href="{game["url"]}">Chess.com ↗</a></span></div>
<div class="viewer"><div>
<div class="boardwrap"><div class="evalbar"><i></i><b></b></div><svg class="board" viewBox="0 0 360 360"><g id="bsq"></g></svg></div>
<div class="ctrl"><button data-go="0" title="début">⏮</button><button data-go="-" title="précédent">◀</button><button data-go="+" title="suivant">▶</button><button data-go="$" title="fin">⏭</button><button id="auto" title="lecture automatique">▶▶</button><button id="flip" title="retourner">⟲</button><button id="undo" title="annuler l'essai" hidden>↩ essai</button><span class="pos" id="pos"></span></div>
<div class="legend">Déplace une pièce pour essayer un coup · <i style="background:#e5533d"></i>joué <i style="background:#3ca63c"></i>meilleur · ← → au clavier</div>
</div><div class="side"><div class="card now" id="now"></div><div class="card moves">{"".join(moves_html)}</div></div></div>
<h2>Courbe d'évaluation</h2><div class="card">{curve_svg(plies, cms, user_white)}
<div class="summary"><span class="k"><i style="background:#e5533d"></i>{sev["blunder"]} gaffes</span><span class="k"><i style="background:#e89b3c"></i>{sev["mistake"]} erreurs</span><span class="k"><i style="background:#e6c84a"></i>{sev["inaccuracy"]} imprécisions</span><span>perte moyenne / coup : <b>{avg:.0f} cp</b></span></div></div>
<h2>Moments critiques ({len(cards)})</h2>{"".join(cards)}
<script>window.__DATA__={json.dumps(data, ensure_ascii=False)};{JS}</script></div></body></html>"""


def index_page(games: list[sqlite3.Row], username: str, served: bool = False) -> str:
    rows = []
    for g in games:
        opp = g["black"] if g["user_color"] == "white" else g["white"]
        link = f"/game/{g['game_number']}" if served else f"game_{g['game_number']}.html"
        rows.append(
            f'<tr><td><a href="{link}">n° {g["game_number"]}</a></td><td>{g["played_at"][:10]}</td>'
            f"<td>{'Blancs' if g['user_color'] == 'white' else 'Noirs'}</td><td>{html.escape(opp)}</td>"
            f'<td class="{g["user_result"]}">{g["user_result"]}</td><td class="dots">{"".join(f"<i style=background:{SEV_COLOR[s]}></i>" for s in (g["sevs"] or "").split(",") if s)}</td></tr>'
        )
    return f"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChessCoach — {html.escape(username)}</title><style>{CSS}</style><body><div class="wrap">
<div class="top"><h1>Bilans de parties · {html.escape(username)}</h1><span class="meta">{len(games)} dernières parties analysées</span></div>
<div class="card" style="padding:0;overflow:auto"><table class="idx"><tr><th>Partie</th><th>Date</th><th>Couleur</th><th>Adversaire</th><th>Résultat</th><th>Moments critiques</th></tr>{"".join(rows)}</table></div>
</div></body></html>"""


def build(conn: sqlite3.Connection, username: str, out_dir: Path, n_games: int) -> list[int]:
    games = conn.execute(
        """SELECT g.*, (SELECT group_concat(severity) FROM (SELECT severity FROM critical_moments cm WHERE cm.game_id = g.id ORDER BY ply)) AS sevs
           FROM games g JOIN analysed_games a ON a.game_id = g.id WHERE g.username = ? ORDER BY g.end_time DESC LIMIT ?""",
        (username, n_games),
    ).fetchall()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(index_page(games, username), encoding="utf-8")
    for g in games:
        (out_dir / f"game_{g['game_number']}.html").write_text(game_page(conn, g), encoding="utf-8")
    return [g["game_number"] for g in games]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--games", type=int, default=10)
    p.add_argument("--out", default="reports/html")
    a = p.parse_args(argv)
    nums = build(db.connect(a.db), a.username, Path(a.out), a.games)
    print(f"{len(nums)} page(s) écrites dans {a.out}/ (index.html)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
