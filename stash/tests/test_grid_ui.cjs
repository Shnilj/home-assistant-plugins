// Render the real grid functions against a minimal DOM; no browser dependency.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.attrs = {}; this.events = {};
    this.classList = {add: name => { this.className += " " + name; }}; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener(name, handler) { this.events[name] = handler; }
  setAttribute(name, value) { this.attrs[name] = value; }
}
const source = fs.readFileSync(path.join(__dirname, "../app/web/static/app.js"), "utf8");
const context = vm.createContext({
  document: {createElement: tag => new Element(tag)},
  requestAnimationFrame: fn => fn(),
});
vm.runInContext(source.replace("  init();", "  globalThis.testGrid = {drawWall, cellLabel, anchorCell};"), context);
const {drawWall} = context.testGrid;
let scenarios = 0;
for (const kind of ["grid", "sorting_box"]) {
  for (const count_cols_from of ["left", "right"]) {
    for (const count_rows_from of ["top", "bottom"]) {
      for (const unitCells of [false, true]) {
        const grid = {kind, cols: 6, rows: 4, count_cols_from, count_rows_from,
          merged_cells: kind === "sorting_box" ? [
            {col: 1, row: 1, cols: 2, rows: 2},
            {col: 3, row: 2, cols: 3, rows: 1},
            {col: 6, row: 1, cols: 1, rows: 4},
          ] : []};
        const clicked = [];
        const holder = drawWall(grid, {}, {unitCells, onTap: c => clicked.push(c)});
        const wall = holder.children[0].children[0];
        const boxes = wall.children.filter(x => x.className === "cellbox" || x.className.startsWith("cellbox "));
        const occupied = new Set();
        for (const box of boxes) {
          const [column, width] = box.style.gridColumn.split(" / span ").map(Number);
          const [row, height] = box.style.gridRow.split(" / span ").map(Number);
          assert(column >= 2 && column + width <= 8);
          assert(row >= 2 && row + height <= 6);
          for (let x = column; x < column + width; x++) {
            for (let y = row; y < row + height; y++) {
              const key = x + "," + y;
              assert(!occupied.has(key), "Overlapping drawn cells: " + key);
              occupied.add(key);
            }
          }
          box.events.click();
          assert(box.attrs["aria-label"]);
        }
        assert.equal(occupied.size, 24);
        assert.equal(boxes.length, kind === "sorting_box" && !unitCells ? 16 : 24);
        assert.equal(new Set(clicked.map(c => c.col + "," + c.row)).size, boxes.length);
        if (unitCells) assert(boxes.every(b => !b.attrs["aria-label"].startsWith("Columns")));
        scenarios++;
      }
    }
  }
}
console.log(scenarios + " grid rendering scenarios passed");
