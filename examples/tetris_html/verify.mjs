// Trusted contract, kept outside the model-writable workspace. No extra packages.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const tests = [];
const test = (name, body) => tests.push([name, body]);
const engine = fs.readFileSync('engine.js', 'utf8');
function check(body) {
  const ctx = vm.createContext({assert});
  try {
    vm.runInContext(engine, ctx, {timeout: 500, filename:'engine.js'});
    vm.runInContext(`const g = new Tetris(); ${body}`, ctx, {timeout: 500, filename:'contract.js'});
  } catch(error) {
    const calls=String(error.stack).split('\n').filter(line=>line.includes('engine.js:')).slice(0,2);
    throw new Error(`${error.message}\n${calls.join('\n')}\nReproduce: ${body.trim().slice(0,320)}`);
  }
}
test('seven shapes, each four valid cells', () => check(`
  const shapes = Array.isArray(Tetris.shapes) ? Tetris.shapes : Object.values(Tetris.shapes);
  assert.equal(shapes.length, 7);
  const forms = new Set();
  for (const [index,s] of shapes.entries()) {
    assert(s.length > 0 && s.every(r => Array.isArray(r) && r.length === s[0].length));
    assert(s.flat().every(Number.isInteger));
    assert.equal(s.flat().filter(Boolean).length, 4, 'shape '+index+' must contain exactly 4 cells: '+JSON.stringify(s));
    forms.add(JSON.stringify(s.map(r => r.map(v => v ? 1 : 0))));
  }
  assert.equal(forms.size, 7);
  function canonical(matrix) {
    let cells=[];matrix.forEach((row,y)=>row.forEach((v,x)=>{if(v)cells.push([x,y]);}));
    const variants=[];
    for(let r=0;r<4;r++) {
      const minX=Math.min(...cells.map(c=>c[0])),minY=Math.min(...cells.map(c=>c[1]));
      variants.push(JSON.stringify(cells.map(([x,y])=>[x-minX,y-minY]).sort((a,b)=>a[0]-b[0]||a[1]-b[1])));
      cells=cells.map(([x,y])=>[-y,x]);
    }
    return variants.sort()[0];
  }
  const expected=[[[1,1,1,1]],[[1,1],[1,1]],[[0,1,0],[1,1,1]],
    [[0,1,1],[1,1,0]],[[1,1,0],[0,1,1]],[[1,0,0],[1,1,1]],[[0,0,1],[1,1,1]]];
  assert.equal(JSON.stringify(shapes.map(canonical).sort()),JSON.stringify(expected.map(canonical).sort()),
    'Use the seven standard connected tetrominos I,O,T,S,Z,J,L');
`));
test('empty independent board rows and initial state', () => check(`
  assert.equal(g.board.length,20); assert(g.board.every(r => r.length===10 && r.every(v=>v===0)));
  assert.equal(g.score,0); assert.equal(g.gameOver,false);
  g.board[0][0]=1; assert.equal(g.board[1][0],0);
`));
test('walls and occupied cells prevent movement', () => check(`
  g.piece=[[1]];g.x=0;g.y=5; assert.equal(g.move(-1),false);assert.equal(g.x,0);
  g.x=9;assert.equal(g.move(1),false);assert.equal(g.x,9);
  g.x=4;g.board[5][5]=2;assert.equal(g.move(1),false);assert.equal(g.x,4);
  assert.equal(g.move(-1),true);assert.equal(g.x,3);
`));
test('tick descends without prematurely locking', () => check(`
  g.piece=[[1]];g.x=4;g.y=2;g.tick();assert.equal(g.y,3);
  assert.equal(g.board.flat().filter(Boolean).length,0);
`));
test('tick locks on the floor without escaping the board', () => check(`
  g.piece=[[1]];g.x=4;g.y=19;g.tick();
  assert.equal(g.board[19][4],1);assert(g.y<5);assert.equal(g.gameOver,false);
`));
test('rotation cycles and preserves static shapes', () => check(`
  const before=JSON.stringify(Tetris.shapes);
  g.piece=[[0,1,0],[1,1,1],[0,0,0]];g.x=3;g.y=3;
  const original=JSON.stringify(g.piece);g.rotate();assert.notEqual(JSON.stringify(g.piece),original);
  g.rotate();g.rotate();g.rotate();assert.equal(JSON.stringify(g.piece),original);
  assert.equal(JSON.stringify(Tetris.shapes),before);
`));
test('blocked rotation preserves piece', () => check(`
  g.piece=[[1,0],[1,1]];g.x=3;g.y=3;g.board[3][4]=2;
  const before=JSON.stringify(g.piece);g.rotate();assert.equal(JSON.stringify(g.piece),before);
`));
test('hard drop lands above floor and spawns', () => check(`
  g.piece=[[1,1],[1,1]];g.x=4;g.y=0;g.hardDrop();
  assert.equal(g.board[18][4],1);assert.equal(g.board[19][5],1);
  assert.equal(g.board.flat().filter(Boolean).length,4);assert(g.y<5);
`));
test('hard drop respects existing blocks', () => check(`
  g.board[19][4]=2;g.piece=[[1]];g.x=4;g.y=0;g.hardDrop();
  assert.equal(g.board[18][4],1);assert.equal(g.board[19][4],2);
`));
test('clear a row and shift the row above down', () => check(`
  g.board[19]=Array(10).fill(2);g.board[19][4]=0;g.board[18][0]=3;
  g.piece=[[1]];g.x=4;g.y=0;g.hardDrop();
  assert.equal(g.score,100);assert.equal(g.board[19][0],3);
  assert.equal(g.board.flat().filter(Boolean).length,1);assert.equal(g.board.length,20);
`));
test('clear adjacent rows together', () => check(`
  for(const y of [18,19]) {g.board[y]=Array(10).fill(2);g.board[y][4]=0;}
  g.piece=[[1],[1]];g.x=4;g.y=0;g.hardDrop();
  assert.equal(g.score,200);assert.equal(g.board.flat().filter(Boolean).length,0);
`));
test('spawn collision causes game over', () => check(`
  for(let y=0;y<6;y++)g.board[y]=Array(10).fill(2);
  g.spawn();assert.equal(g.gameOver,true);
`));
test('game over freezes actions; reset works', () => check(`
  g.gameOver=true;const before=JSON.stringify([g.board,g.piece,g.x,g.y,g.score]);
  g.move(1);g.rotate();g.tick();g.hardDrop();
  assert.equal(JSON.stringify([g.board,g.piece,g.x,g.y,g.score]),before);
  g.reset();assert.equal(g.gameOver,false);assert.equal(g.score,0);
  assert.equal(g.board.flat().filter(Boolean).length,0);
`));
// Execute browser glue with a tiny deterministic DOM and animation clock.
test('HTML wiring: keyboard, gravity, score and restart', () => {
  const html=fs.readFileSync('tetris.html','utf8');
  assert(/src=["'](?:\.\/)?engine\.js["']/.test(html), 'Load local engine.js');
  const listeners={}, frames=[], elements={}, draws=[];
  const canvasTag=html.match(/<canvas\b[^>]*>/i)?.[0] || '';
  const width=Number(canvasTag.match(/width=["'](\d+)["']/)?.[1]);
  const height=Number(canvasTag.match(/height=["'](\d+)["']/)?.[1]);
  assert(width>=200 && height===width*2,'Canvas must display 10 columns x 20 rows of square cells');
  const canvas={clearRect(){},fillRect(...v){assert(v.every(Number.isFinite),'finite drawing coordinates');draws.push(v);},
    strokeRect(){},fillText(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},save(){},restore(){},scale(){}};
  for(const id of ['board','score','status','restart']) {
    assert(new RegExp(`id=["']${id}["']`).test(html), `Missing #${id}`);
    elements[id]={width,height,textContent:'',style:{},getContext:()=>canvas,
      addEventListener:(event,fn)=>{listeners[id+':'+event]=fn;}};
  }
  const document={getElementById:id=>elements[id],querySelector:s=>elements[s.slice(1)],
    addEventListener:(event,fn)=>{listeners[event]=fn;}};
  const ctx=vm.createContext({document,performance:{now:()=>0},
    requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},cancelAnimationFrame(){},
    addEventListener:(event,fn)=>{listeners[event]=fn;}, assert});
  ctx.window=ctx;
  vm.runInContext(engine,ctx,{timeout:500});
  for(const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if(!/\bsrc\s*=/.test(match[1]))vm.runInContext(match[2],ctx,{timeout:500});
  }
  assert(ctx.game instanceof vm.runInContext('Tetris',ctx));
  const g=ctx.game;g.piece=[[1]];g.x=4;g.y=0;
  let prevented=false;
  assert.equal(typeof listeners.keydown,'function');
  listeners.keydown({key:'ArrowLeft',code:'ArrowLeft',preventDefault(){prevented=true;}});
  assert.equal(g.x,3);assert(prevented,'prevent scrolling');
  assert(frames.length,'animation loop');
  for(let t=0;t<=1100;t+=16) {const fn=frames.shift();assert(fn,'keep animating');fn(t);}
  assert(g.y>=2,'accumulate elapsed time: gravity must move at ordinary 60fps');
  g.board[19][9]=7;draws.length=0;frames.shift()(1110);
  assert(draws.some(([x,y])=>Math.abs(x-width*0.9)<1 && Math.abs(y-height*0.95)<1),
    'Render board[row][column] at column*cellSize,row*cellSize, including bottom-right cell');
  g.score=100;frames.shift()(1120);assert(String(elements.score.textContent).includes('100'));
  g.gameOver=true;g.board[19][0]=1;
  frames.shift()(1130);assert(/over|vorbei/i.test(elements.status.textContent),'Show game over');
  const restart=listeners['restart:click'] || elements.restart.onclick;
  assert.equal(typeof restart,'function');restart();
  assert.equal(g.gameOver,false);assert.equal(g.score,0);
  assert.equal(g.board.flat().filter(Boolean).length,0);
  assert(frames.length,'Animation must continue after restart');
});

let passed=0;
const selected=tests.filter(([name]) => process.argv.includes('--engine') ? !name.startsWith('HTML')
  : process.argv.includes('--ui') ? name.startsWith('HTML') : true);
for(const [name,body] of selected) {
  try {body();passed++;} catch(error) {console.log(`FAIL ${name}\n${String(error).slice(0,500)}`);}
}
console.log(JSON.stringify({miniagent_verification:{tests_run:selected.length,tests_passed:passed,
  failures:selected.length-passed,errors:0}}));
process.exitCode=passed===selected.length ? 0 : 1;
