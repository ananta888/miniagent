// Hand-written reference for validating the contract; not a model-generated result.
class Tetris {
  static shapes = [
    [[1,1,1,1]], [[2,2],[2,2]], [[0,3,0],[3,3,3]],
    [[0,4,4],[4,4,0]], [[5,5,0],[0,5,5]],
    [[6,0,0],[6,6,6]], [[0,0,7],[7,7,7]]
  ];
  constructor() { this.reset(); }
  reset() {
    this.board = Array.from({length:20}, () => Array(10).fill(0));
    this.score = 0;
    this.gameOver = false;
    this.spawn();
  }
  fits(piece, x, y) {
    return piece.every((row, dy) => row.every((cell, dx) => !cell ||
      (y+dy >= 0 && y+dy < 20 && x+dx >= 0 && x+dx < 10 && !this.board[y+dy][x+dx])));
  }
  spawn() {
    this.piece = Tetris.shapes[Math.floor(Math.random()*7)].map(row => [...row]);
    this.x = Math.floor((10-this.piece[0].length)/2);
    this.y = 0;
    this.gameOver = !this.fits(this.piece, this.x, this.y);
  }
  move(dx) {
    if (this.gameOver || !this.fits(this.piece, this.x+dx, this.y)) return false;
    this.x += dx;
    return true;
  }
  rotate() {
    if (this.gameOver) return false;
    const rotated = this.piece[0].map((_, x) => this.piece.map(row => row[x]).reverse());
    if (!this.fits(rotated, this.x, this.y)) return false;
    this.piece = rotated;
    return true;
  }
  lock() {
    this.piece.forEach((row, y) => row.forEach((cell, x) => {
      if (cell) this.board[this.y+y][this.x+x] = cell;
    }));
    const remaining = this.board.filter(row => row.some(cell => !cell));
    const cleared = 20-remaining.length;
    this.score += cleared*100;
    this.board = [...Array.from({length:cleared}, () => Array(10).fill(0)), ...remaining];
    this.spawn();
  }
  tick() {
    if (this.gameOver) return;
    if (this.fits(this.piece, this.x, this.y+1)) this.y++;
    else this.lock();
  }
  hardDrop() {
    if (this.gameOver) return;
    while (this.fits(this.piece, this.x, this.y+1)) this.y++;
    this.lock();
  }
}
globalThis.Tetris = Tetris;
