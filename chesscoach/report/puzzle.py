"""Page de puzzles jouable : un puzzle Lichess résolu directement dans l'échiquier maison.

Toutes les positions, les coups légaux et la solution sont précalculés par python-chess ; le JS ne
fait qu'afficher et comparer. ``build(conn, username, tag, n)`` retourne une page autonome, servie
par ``/puzzle`` et ``/puzzle/<tag>``.
"""

from __future__ import annotations

import html
import json
import sqlite3

import chess

from chesscoach.memory.fsrs import due_tags, load_card
from chesscoach.report.board import BOARD_JS, legal_moves, piece_symbols
from chesscoach.report.html import CSS
from chesscoach.report.render import TAG_LABEL
from chesscoach.puzzles.select import pick
from chesscoach.taxonomy.tags import Tag

JS = """
const D=window.__DATA__;let k=0;let step=0;let sel=null;let wrong=false;let done=false;let msg='';
const svg=$('svg.board');
function P(){return D.puzzles[k]}
function cur(){return P().steps[step]}
function legalFrom(f,r){const from='abcdefgh'[f]+(r+1);return (cur().legal||[]).filter(c=>c.startsWith(from))}
function show(){const p=P();const st=cur();const extra={hl:[],dots:[]};
if(step>0){const m=p.steps[step-1].move;extra.hl.push([...uciSq(m.slice(0,2)),'#f6f669'],[...uciSq(m.slice(2,4)),'#f6f669'])}
if(sel){extra.hl.push([sel[0],sel[1],'#f6f669']);const b=parseFen(st.fen);for(const c of legalFrom(sel[0],sel[1])){const t=uciSq(c.slice(2,4));extra.dots.push([t[0],t[1],!!b[t[0]+','+t[1]]])}}
if(done&&p.steps.length){const m=p.steps[p.steps.length-1].move;extra.arrows=[[...uciSq(m.slice(0,2)),...uciSq(m.slice(2,4)),'#3ca63c','green']]}
$('#bsq').innerHTML=renderBoard(st?st.fen:p.final_fen,extra);
const turn=(st?st.fen:p.final_fen).split(' ')[1]==='w'?'Les blancs jouent':'Les noirs jouent';
const head=`<div class="ev" style="text-transform:uppercase;letter-spacing:.06em;font-size:.75rem">Puzzle ${k+1}/${D.puzzles.length} · ${p.tag_label} · cote ${p.rating}</div>`;
let body;
if(done)body=`<div class="mv" style="color:${wrong?'var(--blue)':'var(--green)'}">${wrong?'Résolu (avec erreur)':'Résolu du premier coup ✔'}</div><div class="ev">${msg}</div>
<div style="margin-top:10px">${k+1<D.puzzles.length?'<button class="btn" id="next">Puzzle suivant</button>':'<a class="btn" href="/">Retour aux parties</a>'} <a class="ev" style="margin-left:8px" href="${p.url}" target="_blank">voir sur Lichess ↗</a></div>`;
else if(st.side==='user')body=`<div class="mv">${turn} — à toi</div><div class="ev">${msg||'Trouve le coup.'}</div><div style="margin-top:10px"><button class="btn" id="giveup">Montrer la solution</button></div>`;
else body=`<div class="mv">${turn}</div><div class="ev">Coup adverse…</div>`;
$('#now').innerHTML=head+body;
const nx=$('#next');if(nx)nx.onclick=()=>{k++;step=0;sel=null;wrong=false;done=false;msg='';flip=D.puzzles[k].flip;show()};
const gu=$('#giveup');if(gu)gu.onclick=()=>{wrong=true;play(cur().move,true)};
if(st&&st.side==='opponent'){setTimeout(()=>{if(cur()===st)play(st.move,false)},600)}}
function finish(){done=true;msg=wrong?'':'';
fetch('/api/puzzle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({puzzle_id:P().id,tag:P().tag,solved:true,first_try:!wrong})})
.then(r=>r.json()).then(j=>{msg=j.ok?'enregistré ✓ · prochaine révision '+(j.due||'—'):'erreur : '+j.error;show()}).catch(()=>{msg='serveur injoignable';show()});show()}
function play(code,forced){step++;sel=null;if(step>=P().steps.length){finish();return}show()}
function tryMove(f1,r1,f2,r2){const from='abcdefgh'[f1]+(r1+1),to='abcdefgh'[f2]+(r2+1);const codes=(cur().legal||[]).filter(c=>c.startsWith(from+to));
if(!codes.length)return false;const code=codes.find(c=>c[4]==='q')||codes[0];
if(code.slice(0,4)===cur().move.slice(0,4)){msg='';play(code,false)}else{wrong=true;msg='Non : '+sanOf(cur().fen,code)+' n\\'est pas la solution. Réessaie.';sel=null;show()}
return true}
let drag=null;
svg.addEventListener('pointerdown',ev=>{if(done||cur().side!=='user')return;const s=squareAt(svg,ev);if(!s)return;const b=parseFen(cur().fen);const pc=b[s.join(',')];const turn=cur().fen.split(' ')[1];
if(sel&&tryMove(sel[0],sel[1],s[0],s[1]))return;
if(pc&&((turn==='w')===(pc===pc.toUpperCase()))&&legalFrom(s[0],s[1]).length){sel=s;show();const el=[...svg.querySelectorAll('.pc')].find(e=>+e.dataset.f===s[0]&&+e.dataset.r===s[1]);drag={from:s,el};svg.setPointerCapture(ev.pointerId)}else{sel=null;show()}});
svg.addEventListener('pointermove',ev=>{if(!drag||!drag.el)return;const pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());drag.el.setAttribute('x',p.x-22.5);drag.el.setAttribute('y',p.y-22.5);drag.el.style.pointerEvents='none';drag.moved=true});
svg.addEventListener('pointerup',ev=>{if(!drag)return;const s=squareAt(svg,ev);const d=drag;drag=null;if(s&&d.moved&&!(s[0]===d.from[0]&&s[1]===d.from[1])){if(!tryMove(d.from[0],d.from[1],s[0],s[1])){sel=null;show()}}else if(d.moved){show()}});
$('#flip').onclick=()=>{flip=!flip;show()};
flip=P().flip;show();
"""


def puzzle_payload(row: sqlite3.Row, tag: str) -> dict:
    """Déroule un puzzle Lichess : FEN de départ, coup d'amorce adverse, puis alternance."""
    board = chess.Board(row["fen"])
    steps = []
    for idx, uci in enumerate(row["moves"].split()):
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            break
        kind = "c" if board.is_castling(move) else "e" if board.is_en_passant(move) else "p" if move.promotion else "n"
        steps.append(
            {
                "fen": board.fen(),
                "legal": legal_moves(board),
                "move": uci + kind,
                "san": board.san(move),
                "side": "opponent" if idx % 2 == 0 else "user",
            }
        )
        board.push(move)
    user_white = steps[1]["fen"].split()[1] == "w" if len(steps) > 1 else board.turn
    return {
        "id": row["id"],
        "rating": row["rating"],
        "themes": row["themes"],
        "tag": tag,
        "tag_label": TAG_LABEL[tag],
        "url": f"https://lichess.org/training/{row['id']}",
        "steps": steps,
        "final_fen": board.fen(),
        "flip": not user_white,
    }


def next_tag(conn: sqlite3.Connection, username: str) -> str | None:
    """Tag à travailler : le plus en retard selon FSRS, sinon le plus fréquent non retiré."""
    due = due_tags(conn, username)
    if due:
        return due[0][0]
    row = conn.execute(
        """SELECT cm.primary_tag AS tag, count(*) AS n FROM critical_moments cm JOIN games g ON g.id = cm.game_id
           WHERE g.username = ? GROUP BY cm.primary_tag ORDER BY n DESC""",
        (username,),
    ).fetchall()
    for r in row:
        card = load_card(conn, username, r["tag"])
        if (card is None or card.state != "retired") and r["tag"] in {t.value for t in Tag}:
            if conn.execute(
                "SELECT 1 FROM puzzles WHERE (',' || tags || ',') LIKE ('%,' || ? || ',%')", (r["tag"],)
            ).fetchone():
                return r["tag"]
    return None


def build(conn: sqlite3.Connection, username: str, tag: str | None = None, n: int = 3) -> str:
    tag = tag or next_tag(conn, username)
    if tag is None:
        return _empty("Aucun tag à travailler : lance une session, ou importe des puzzles.")
    rows = pick(conn, username, tag, n=n)
    payloads = [puzzle_payload(r, tag) for r in rows]
    payloads = [p for p in payloads if len(p["steps"]) >= 2]
    if not payloads:
        return _empty(
            f"Aucun puzzle disponible pour « {TAG_LABEL[tag]} » "
            "(base vide, ou tous déjà tentés). Importe la base : "
            "<code>python -m chesscoach.puzzles.lichess</code>."
        )
    data = {"puzzles": payloads}
    return f"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Puzzles — {html.escape(TAG_LABEL[tag])}</title><style>{CSS}</style><body><div class="wrap">{piece_symbols()}
<div class="top"><h1>Puzzles · {html.escape(TAG_LABEL[tag])}</h1><a href="/">← les parties</a></div>
<div class="meta"><span>{len(payloads)} puzzle(s)</span><span>source : base Lichess (CC0)</span><span><a href="/progress">progression →</a></span></div>
<div class="viewer"><div>
<div class="boardwrap"><svg class="board" viewBox="0 0 360 360"><g id="bsq"></g></svg></div>
<div class="ctrl"><button id="flip" title="retourner">⟲</button></div>
<div class="legend">Joue le meilleur coup pour le camp au trait. Les coups légaux viennent de python-chess.</div>
</div><div class="side"><div class="card now" id="now"></div></div></div>
<script>window.__DATA__={json.dumps(data, ensure_ascii=False)};{BOARD_JS}{JS}</script></div></body></html>"""


def _empty(message: str) -> str:
    return (
        f'<!doctype html><html lang="fr"><meta charset="utf-8"><title>Puzzles</title><style>{CSS}</style>'
        f'<body><div class="wrap"><div class="top"><h1>Puzzles</h1><a href="/">← les parties</a></div>'
        f'<div class="card">{message}</div></div></body></html>'
    )
