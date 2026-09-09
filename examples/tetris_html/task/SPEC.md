# Playable Tetris

Create engine.js and tetris.html, using local files only. No libraries or network.
The old example was broken. Separate the small game engine from browser rendering.

engine.js exposes globalThis.Tetris, a class with static shapes: an array of seven distinct
rectangular numeric matrices for I,O,T,S,Z,J,L. Each has exactly four occupied cells.
Instance fields: board (20 rows of 10 numeric cells, 0 empty), piece (matrix),
x and y (integer position of piece top-left), score (number), gameOver (boolean).
Constructor calls reset(). Copy shapes before rotation; never mutate Tetris.shapes.
Methods: reset(), spawn(), move(dx), rotate(), tick(), hardDrop().
move(dx) returns false and preserves x on wall/occupied collision, otherwise true.
rotate() rotates clockwise only when the rotated piece fits; on failure preserve it.
tick() moves down one row or locks, clears full rows, and spawns the next piece.
hardDrop() lands and locks without overlap, clears rows, then spawns.
Clearing rows shifts everything above down and inserts empty rows at the top;
award 100 points per row, with no other scoring. Game over when a new piece collides.
After gameOver, movement, rotation, tick and hardDrop do nothing. reset clears it.
Tests can assign board, piece, x, y, score and gameOver directly to construct fixtures.

tetris.html loads engine.js using a regular script tag (works via file://).
Expose window.game = new Tetris(). Draw board and active piece on canvas#board.
Use a 240x480 canvas, 24px square cells: column is x, row is y.
Use distinct visible colors. Show #score and #status and button#restart.
ArrowLeft/Right call move(-1/1), ArrowUp rotate, ArrowDown tick, Space hardDrop.
Prevent page scrolling for these keys. Use requestAnimationFrame with accumulated
elapsed time, calling tick every 500 milliseconds. Redraw after inputs and ticks.
Show Game Over. Restart resets game, gravity timer and screen; animation continues.
Include a short German instruction, a title, score and restart button.
