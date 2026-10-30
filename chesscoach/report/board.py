"""Échiquier SVG interactif partagé (bilan de partie et puzzles) : rendu et manipulation en JS,
mais **aucune règle d'échecs** — les coups légaux sont toujours précalculés par python-chess."""

from __future__ import annotations

import chess
import chess.svg


def piece_symbols() -> str:
    """Les 12 pièces SVG de python-chess en <symbol>, plus les pointes de flèches, une seule fois."""
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
        for n, c in (("red", "#e5533d"), ("green", "#3ca63c"), ("blue", "#7fb3e5"))
    )
    return f'<svg width="0" height="0" style="position:absolute"><defs>{"".join(out)}{arrows}</defs></svg>'


def legal_moves(board: chess.Board) -> list[str]:
    """Coups légaux encodés « uci + type » : n normal, c roque, e prise en passant, p promotion."""
    out = []
    for m in board.legal_moves:
        kind = "c" if board.is_castling(m) else "e" if board.is_en_passant(m) else "p" if m.promotion else "n"
        out.append(m.uci() + kind)
    return out


# JS partagé : rendu de l'échiquier et application d'un coup déjà validé côté Python.
BOARD_JS = """
const $=q=>document.querySelector(q);let flip=false;
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
function sanOf(fen,code){const b=parseFen(fen);const pc=b[uciSq(code.slice(0,2)).join(',')]||'';const cap=!!b[uciSq(code.slice(2,4)).join(',')]||code.endsWith('e');const k=code[code.length-1];
if(k==='c')return code[2]==='g'?'O-O':'O-O-O';const P=pc.toUpperCase()==='P'?(cap?code[0]:''):pc.toUpperCase();return P+(cap?'x':'')+code.slice(2,4)+(k==='p'?'='+code[4].toUpperCase():'')}
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
function squareAt(svg,ev){const pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());const x=Math.floor(p.x/45),y=7-Math.floor(p.y/45);if(x<0||x>7||y<0||y>7)return null;return flip?[7-x,7-y]:[x,y]}
"""
