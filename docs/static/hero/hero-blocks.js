/* ==========================================================================
   NCE — hero background
   --------------------------------------------------------------------------
   The context, as a ledger.

   Blocks live in ruled columns. Each column is a stack of addressable
   context blocks: an address in the left margin, a hairline rule, a body
   with a type rail and a few lines of text. The columns drift upward at
   parallax speeds — the outer ones near and fast, the middle ones far and
   slow — while every few seconds an edit lands: a block is rewritten (an
   amber flash), deleted (the block collapses and the column reflows to
   close the gap), or appended (a new block slides into the stack and the
   blocks below make room).

   The reflow is the point. It is the one thing in the hero that behaves
   like the paper's subject rather than like decoration.

   Canvas 2D, drawn procedurally each frame, no dependencies, no network.

   Usage — declarative (the script picks the canvas up on load):

     <canvas data-hero-blocks></canvas>
     <script src="static/hero/hero-blocks.js" defer></script>

   or imperative, with per-instance parameters:

     HeroBlocks.attach(canvas, { alpha: 0.9, columns: 7, edits: 1.2 });

   Colours come from the page's tokens (--block-system, --block-task,
   --series-tools, --block-note, --block-rewritten) and follow
   <html data-theme="dark|light">, falling back to the OS preference.
   ========================================================================== */
(function (global, doc) {
  "use strict";

  var VERSION = "4.0.0";

  var DEFAULTS = {
    columns: null,         /* null = derive from width (one per ~200px) */
    minColumns: 3,
    maxColumns: 8,
    speed: 1,              /* global time scale */
    alpha: 1,              /* overall opacity of the field */
    edits: 1,              /* edit-event rate multiplier; 0 stops the grammar */
    editEvery: [0.38, 0.62], /* seconds between edits: [min, max] (~2/s) */
    reducedMotion: "static",
    stillTime: 40,
    dpr: 2,
    seed: 20261017
  };

  var ROLES = ["tool", "task", "tool", "note", "task", "tool", "system"];

  var TYPE_FALLBACK = {
    light: { system: "#3A4352", task: "#2563EB", tool: "#7C8CA6", note: "#2C6A3B", rewritten: "#DFA032" },
    dark:  { system: "#4A5568", task: "#93C5FD", tool: "#9AA4B6", note: "#8FD19E", rewritten: "#DFA032" }
  };

  /* ---------------------------------------------------------------------- */
  /* helpers                                                              */
  /* ---------------------------------------------------------------------- */

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function lerp(a, b, t) { return a + (b - a) * t; }

  function smooth01(x) {
    x = x < 0 ? 0 : x > 1 ? 1 : x;
    return x * x * (3 - 2 * x);
  }

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function cssVar(name) {
    try {
      return global.getComputedStyle(doc.documentElement).getPropertyValue(name).trim();
    } catch (e) { return ""; }
  }

  function readOptions(el, user) {
    var o = {}, k;
    for (k in DEFAULTS) {
      if (Object.prototype.hasOwnProperty.call(DEFAULTS, k)) o[k] = DEFAULTS[k];
    }
    var data = {
      columns: "columns", speed: "speed", alpha: "alpha",
      edits: "edits", motion: "reducedMotion", dpr: "dpr"
    };
    for (var attr in data) {
      if (!Object.prototype.hasOwnProperty.call(data, attr)) continue;
      var raw = el.getAttribute("data-" + attr);
      if (raw === null) continue;
      var key = data[attr];
      if (key === "reducedMotion") o[key] = raw;
      else {
        var num = parseFloat(raw);
        if (!isNaN(num)) o[key] = num;
      }
    }
    if (user) {
      for (k in user) {
        if (Object.prototype.hasOwnProperty.call(user, k) && user[k] !== undefined) o[k] = user[k];
      }
    }
    return o;
  }

  /* An address the way a block id reads in the paper: a base-36 pair, a dot,
     another pair. Unique per block — the identity is the whole point. */
  function makeAddress(rnd) {
    var digits = "0123456789abcdefghijklmnopqrstuvwxyz";
    function pair() {
      return digits[Math.floor(rnd() * 36)] + digits[Math.floor(rnd() * 36)];
    }
    return pair() + "·" + pair();
  }

  function roundRect(g, x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  /* ---------------------------------------------------------------------- */
  /* the ledger                                                           */
  /* ---------------------------------------------------------------------- */

  function attach(canvas, userOptions) {
    if (!canvas) return null;
    if (canvas.__heroBlocks) return canvas.__heroBlocks;

    var opts = readOptions(canvas, userOptions);
    var g = null;
    try {
      g = canvas.getContext("2d", { alpha: true, desynchronized: true });
    } catch (e) { g = null; }

    var api = {
      version: VERSION,
      available: !!g,
      options: opts,
      stats: { frames: 0, fps: 0, cpuMs: 0 },
      destroy: destroy,
      redraw: null
    };

    if (!g) {
      canvas.style.display = "none";
      if (global.console && console.warn) {
        console.warn("[hero-blocks] Canvas 2D unavailable; leaving the static scrim.");
      }
      canvas.__heroBlocks = api;
      return api;
    }

    /* ---- palette ------------------------------------------------------- */

    var rnd = mulberry32(opts.seed);
    var themeName = "light";
    var pal = null;
    var mqDark = global.matchMedia ? global.matchMedia("(prefers-color-scheme: dark)") : null;
    var mqReduce = global.matchMedia ? global.matchMedia("(prefers-reduced-motion: reduce)") : null;

    function buildPalette() {
      var dark = themeName === "dark";
      var fb = TYPE_FALLBACK[themeName] || TYPE_FALLBACK.light;
      var rail = {
        system: cssVar("--block-system") || fb.system,
        task: cssVar("--block-task") || fb.task,
        tool: cssVar(dark ? "--block-tool" : "--series-tools") || fb.tool,
        note: cssVar("--block-note") || fb.note,
        rewritten: cssVar("--block-rewritten") || fb.rewritten
      };
      pal = {
        dark: dark,
        card: dark ? "rgba(19, 28, 47, 0.70)" : "rgba(255, 255, 255, 0.92)",
        edge: dark ? "rgba(141, 180, 240, 0.16)" : "rgba(28, 34, 48, 0.16)",
        rule: dark ? "rgba(147, 197, 253, 0.10)" : "rgba(37, 99, 235, 0.085)",
        address: dark ? "rgba(232, 236, 244, 0.40)" : "rgba(28, 34, 48, 0.40)",
        bar: dark ? "rgba(232, 236, 244, 0.30)" : "rgba(28, 34, 48, 0.30)",
        barSoft: dark ? "rgba(232, 236, 244, 0.13)" : "rgba(28, 34, 48, 0.15)",
        hot: rail.rewritten,
        rewrite: rail.rewritten || "#DFA032",
        drop: cssVar("--chip-drop-fg") || (dark ? "#F2958F" : "#A1282A"),
        append: cssVar("--chip-append-fg") || (dark ? "#8FD19E" : "#2C6A3B"),
        dropWash: cssVar("--chip-drop-bg") || (dark ? "#4A1F22" : "#F7D3D1"),
        appendWash: cssVar("--chip-append-bg") || (dark ? "#1F3D27" : "#D6EDDA"),
        rewriteWash: cssVar("--chip-rewrite-bg") || (dark ? "#4A3613" : "#FAE1B0"),
        rail: rail
      };
    }

    /* ---- state --------------------------------------------------------- */

    var cssW = 1, cssH = 1, dpr = 1;
    var columns = [];
    var time = 0;
    var nextEdit = 0.5;
    var raf = 0, last = 0;
    var hidden = doc.visibilityState === "hidden";
    var inView = true;
    var stopped = false;
    var drawnStill = false;
    var editsFired = 0;
    var editedNow = 0;
    var cpuEma = 0;
    var fpsFrames = 0, fpsSince = 0;
    var fallbackResize = false;
    var themeObserver = null, resizeObserver = null, intersection = null;

    /* ---- blocks & columns ---------------------------------------------- */

    function newBlock(col) {
      /* Height is per block, not per column: most blocks are one line tall,
         some are two, and now and then one is a tall block with more text.
         That irregularity is what makes a column read as a context rather
         than as a table. */
      var roll = rnd();
      var tall = roll > 0.86;
      var two = !tall && roll > 0.52;

      var barCount = tall ? 4 + (rnd() > 0.6 ? 1 : 0) : two ? 3 : 2;
      var bars = [];
      for (var i = 0; i < barCount; i++) {
        bars.push(clamp(0.88 - i * 0.16 + (rnd() - 0.5) * 0.24, 0.18, 0.98));
      }

      var h = tall ? Math.round(col.h * 1.55) : two ? Math.round(col.h * 1.18) : col.h;

      return {
        role: ROLES[Math.floor(rnd() * ROLES.length)],
        address: makeAddress(rnd),
        bars: bars,
        h: h,
        y: 0,          /* animated position inside the column */
        target: 0,     /* layout position, recomputed each pass */
        alphaIn: 1,
        op: 0,        /* 1 = rewrite (amber), 2 = drop (red), 3 = append (green) */
        opT: 0,       /* 1 → 0 over the edit's lifetime */
        opAfter: 0,   /* lingers after the animation, so a rewrite stays marked */
        edited: false
      };
    }

    function buildColumns() {
      var n = opts.columns;
      if (!n) n = clamp(Math.round(cssW / 200), opts.minColumns, opts.maxColumns);
      n = clamp(Math.round(n), opts.minColumns, opts.maxColumns);

      var margin = Math.max(14, cssW * 0.032);
      var step = (cssW - margin * 2) / n;
      var mid = (n - 1) / 2;

      columns = [];
      for (var i = 0; i < n; i++) {
        /* Depth: the centre column sits furthest away, the edges come
           forward. That keeps the middle quiet behind the headline. */
        var spread = mid === 0 ? 0 : Math.abs(i - mid) / mid;
        var depth = 0.22 + 0.78 * Math.pow(spread, 0.75);
        var cardW = Math.round(step * (0.60 + 0.06 * depth));
        var h = Math.round(lerp(23, 42, depth));
        var gap = Math.max(12, Math.round(h * 0.62));
        var slot = h + gap;

        var col = {
          index: i,
          x: margin + step * (i + 0.5),
          cardW: cardW,
          h: h,
          gap: gap,
          depth: depth,
          speed: (7 + 17 * depth) * (0.9 + rnd() * 0.2),
          scroll: 0,
          blocks: []
        };

        var need = Math.ceil((cssH + h * 2) / slot) + 2;
        for (var k = 0; k < need; k++) {
          var b = newBlock(col);
          b.y = k * slot;
          b.target = b.y;
          col.blocks.push(b);
        }
        /* Start each column at a different phase so the tops do not align. */
        col.scroll = rnd() * slot;
        columns.push(col);
      }
    }

    /* Recompute every block's layout position top-down, each at its own
       height. */
    function layout(col) {
      var y = 0;
      for (var i = 0; i < col.blocks.length; i++) {
        var b = col.blocks[i];
        b.target = y;
        y += b.h + col.gap;
      }
    }

    /* ---- edit grammar -------------------------------------------------- */

    function fireEdit() {
      if (!columns.length) return;

      /* Favour the near columns: they are the ones a visitor can actually
         see happening. */
      var pool = [], weights = [];
      for (var c = 0; c < columns.length; c++) {
        pool.push(columns[c]);
        weights.push(0.3 + columns[c].depth);
      }
      var total = 0;
      for (var w = 0; w < weights.length; w++) total += weights[w];
      var pick = rnd() * total, chosen = pool[0];
      for (var p = 0; p < pool.length; p++) {
        pick -= weights[p];
        if (pick <= 0) { chosen = pool[p]; break; }
      }
      var col = chosen;

      /* Only edit blocks that are actually on screen, and never one that is
         already mid-edit — two overlays on the same card read as a glitch. */
      var visible = [];
      for (var i = 0; i < col.blocks.length; i++) {
        var b = col.blocks[i];
        var sy = b.y - col.scroll;
        if (sy > 20 && sy < cssH - b.h - 20 && b.op === 0) visible.push(i);
      }
      if (!visible.length) return;
      var at = visible[Math.floor(rnd() * visible.length)];
      var block = col.blocks[at];
      var roll = rnd();
      editsFired++;

      if (roll < 0.40) {
        /* rewrite — amber. The card is outlined in amber, a sweep crosses it
           left to right, and the first line becomes the rewritten line. */
        block.op = 1;
        block.opT = 1;
        block.edited = true;
      } else if (roll < 0.74 && col.blocks.length > 5) {
        /* drop — red. The card is struck through in red, then collapses
           upward and the column closes the gap behind it. */
        block.op = 2;
        block.opT = 1;
      } else {
        var totalBlocks = 0;
        for (var t = 0; t < columns.length; t++) totalBlocks += columns[t].blocks.length;
        if (totalBlocks >= opts.maxBlocks) {
          /* At the population ceiling an append would push the oldest block
             out of some other column; a rewrite is the better edit. */
          block.op = 1;
          block.opT = 1;
          block.edited = true;
          layout(col);
          return;
        }
        /* append — green. A new card fades and slides in where the edit
           landed, drawing the green rail of an appended note. */
        var nb = newBlock(col);
        var idx = clamp(at + 1, 1, col.blocks.length);
        col.blocks.splice(idx, 0, nb);
        layout(col);
        nb.y = nb.target + nb.h * 0.7;
        nb.alphaIn = 0;
        nb.role = "note";
        nb.op = 3;
        nb.opT = 1;
      }
      layout(col);
    }

    /* ---- sizing -------------------------------------------------------- */

    function resize() {
      var rect = canvas.getBoundingClientRect();
      var w = Math.max(1, Math.round(rect.width));
      var h = Math.max(1, Math.round(rect.height));
      dpr = Math.min(global.devicePixelRatio || 1, opts.dpr);
      if (w === cssW && h === cssH && canvas.width === Math.round(w * dpr)) return;
      cssW = w;
      cssH = h;
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      buildColumns();
      draw();
    }

    /* ---- simulation ---------------------------------------------------- */

    function advance(dt) {
      if (dt <= 0) return;
      time += dt * opts.speed;

      if (opts.edits > 0 && time >= nextEdit) {
        fireEdit();
        var lo = opts.editEvery[0], hi = opts.editEvery[1];
        nextEdit = time + (lo + rnd() * (hi - lo)) / Math.max(0.2, opts.edits);
      }

      var ease = 1 - Math.exp(-dt * 9);

      for (var c = 0; c < columns.length; c++) {
        var col = columns[c];
        col.scroll += col.speed * dt * opts.speed;

        var first = col.blocks[0];
        while (first && first.y + first.h - col.scroll < -first.h * 2) {
          var removed = first.h + col.gap;
          col.blocks.shift();
          col.scroll -= removed;
          for (var r = 0; r < col.blocks.length; r++) col.blocks[r].y -= removed;

          var nb = newBlock(col);
          col.blocks.push(nb);
          layout(col);
          nb.y = nb.target;
          nb.alphaIn = 1;
          first = col.blocks[0];
        }

        layout(col);
        for (var i = col.blocks.length - 1; i >= 0; i--) {
          var b = col.blocks[i];
          b.y += (b.target - b.y) * ease;
          if (b.alphaIn < 1) b.alphaIn = Math.min(1, b.alphaIn + dt / 0.5);

          if (b.op > 0) {
            b.opT -= dt / (b.op === 2 ? 0.72 : 0.95);
            if (b.op === 2) {
              /* once a drop has finished collapsing, take it out and let the
                 column close the gap */
              if (b.opT <= 0) {
                col.blocks.splice(i, 1);
                layout(col);
                continue;
              }
            } else if (b.opT <= 0) {
              b.op = 0;                 /* the animation ends; edited stays */
              b.opT = 0;
            }
          }
        }
      }
    }

    /* ---- drawing ------------------------------------------------------- */

    function draw() {
      if (!g) return;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, cssW, cssH);

      var margin = Math.max(14, cssW * 0.032);
      for (var c = 0; c < columns.length; c++) {
        drawColumn(columns[c], margin);
      }
      g.globalAlpha = 1;
    }

    function drawColumn(col, margin) {
      var ruleX = col.x - col.cardW / 2 - col.gap * 1.1;

      /* the ruled line: the ledger's structure */
      if (ruleX > margin * 0.4) {
        g.globalAlpha = (0.5 + 0.5 * col.depth) * opts.alpha;
        g.strokeStyle = pal.rule;
        g.lineWidth = 1;
        g.beginPath();
        g.moveTo(Math.round(ruleX) + 0.5, 0);
        g.lineTo(Math.round(ruleX) + 0.5, cssH);
        g.stroke();
      }

      for (var i = 0; i < col.blocks.length; i++) {
        drawBlock(col, col.blocks[i], ruleX);
      }
      g.globalAlpha = 1;
    }

    /* The colour an edit is drawn in. Rewrite is amber, drop red, append
       green — the three operator chips the paper already uses. */
    function opColor(op) {
      return op === 2 ? pal.drop : op === 3 ? pal.append : pal.rewrite;
    }
    function opWash(op) {
      return op === 2 ? pal.dropWash : op === 3 ? pal.appendWash : pal.rewriteWash;
    }

    function drawBlock(col, b, ruleX) {
      var sy = b.y - col.scroll;
      if (sy > cssH + b.h || sy < -b.h * 2.5) return;

      var w = col.cardW;
      var h = b.h;
      var x = col.x - w / 2;
      var a = (0.30 + 0.70 * col.depth) * opts.alpha * b.alphaIn;
      if (a <= 0.005) return;

      /* A live edit swells the card a little, so the eye finds it first. */
      var e = b.op ? smooth01(b.opT) : 0;
      var grow = 1 + 0.055 * e;
      var dw = w * grow, dh = h * grow;
      x -= (dw - w) / 2;
      sy -= (dh - h) / 2;
      w = dw; h = dh;
      if (b.op === 2) {
        /* a drop squashes upward as it goes */
        var k = 1 - Math.pow(b.opT, 0.72);
        h = dh * (1 - 0.55 * k);
      }

      var fs = 9.5;
      var acol = b.op ? opColor(b.op) : (b.edited ? pal.hot : pal.address);

      /* address in the left margin */
      if (ruleX - marginish(col) > 22) {
        g.globalAlpha = a * (b.op ? 1 : 0.9);
        g.font = (b.op ? "700 " : "500 ") + fs.toFixed(1) + "px ui-monospace, Menlo, Consolas, monospace";
        g.textAlign = "right";
        g.textBaseline = "middle";
        g.fillStyle = acol;
        g.fillText(b.address, ruleX - 7, sy + h / 2);
      }

      /* body */
      g.globalAlpha = a;
      g.beginPath();
      roundRect(g, x, sy, w, h, 4);           /* 4px — the chip radius */
      g.fillStyle = pal.card;
      g.fill();

      /* operator wash: a tinted fill inside the card while the edit plays */
      if (b.op) {
        g.globalAlpha = a * 0.55 * e;
        g.fillStyle = opWash(b.op);
        g.fill();
        g.globalAlpha = a;
      }

      /* frame: hairline at rest, 2px in the operator colour with a soft halo
         while editing */
      if (b.op && e > 0.01) {
        g.save();
        g.globalAlpha = a * 0.20 * e;
        g.strokeStyle = opColor(b.op);
        g.lineWidth = 7;
        g.beginPath();
        roundRect(g, x - 2, sy - 2, w + 4, h + 4, 6);
        g.stroke();
        g.restore();

        g.globalAlpha = a;
        g.lineWidth = 2;
        g.strokeStyle = opColor(b.op);
      } else {
        g.globalAlpha = a;
        g.lineWidth = 1;
        g.strokeStyle = b.edited ? pal.rewrite : pal.edge;
      }
      g.beginPath();
      roundRect(g, x, sy, w, h, 4);
      g.stroke();
      g.globalAlpha = a;

      /* type rail — an appended block carries the append colour instead */
      var railW = Math.max(3, Math.round(h * 0.09));
      g.save();
      g.beginPath();
      roundRect(g, x, sy, w, h, 4);
      g.clip();
      g.fillStyle = b.op === 3 ? pal.append : pal.rail[b.role] || pal.rail.tool;
      g.fillRect(x, sy, railW, h);

      /* the sweep: a band of amber crossing the card left to right during a
         rewrite */
      if (b.op === 1 && b.opT > 0.35) {
        var sw = (1 - b.opT) / 0.65;
        var bandX = x + w * clamp(sw * 1.6 - 0.3, -0.5, 1.2);
        g.globalAlpha = a * 0.30 * e;
        g.fillStyle = pal.rewrite;
        g.fillRect(bandX, sy, w * 0.22, h);
      }
      g.restore();
      g.globalAlpha = a;

      /* lines of text */
      var bx = x + railW + clamp(h * 0.30, 4, 8);
      var avail = x + w - bx - clamp(h * 0.26, 4, 8);
      var barH = Math.max(2, h * 0.075);
      var gap = barH * 2.0;
      var n = b.bars.length;
      var totalH = n * barH + (n - 1) * (gap - barH);
      var y0 = sy + (h - totalH) / 2;

      for (var i = 0; i < n; i++) {
        var bw = Math.max(4, avail * b.bars[i]);
        g.beginPath();
        roundRect(g, bx, y0 + i * gap, bw, barH, barH / 2);
        if (b.op === 1) g.fillStyle = i === 0 ? pal.rewrite : pal.bar;
        else if (b.op === 2) g.fillStyle = pal.drop;
        else if (b.op === 3) g.fillStyle = pal.append;
        else g.fillStyle = b.edited && i === 0 ? pal.hot : i === 0 ? pal.bar : pal.barSoft;
        if (b.op === 3) g.globalAlpha = a * (0.30 + 0.70 * b.opT);
        g.fill();
        g.globalAlpha = a;
      }

      /* the strike-through on a drop, and the operator label on all three */
      if (b.op && e > 0.02) {
        if (b.op === 2) {
          var p2 = 1 - b.opT;
          g.globalAlpha = a * 0.85;
          g.strokeStyle = pal.drop;
          g.lineWidth = Math.max(1.5, h * 0.055);
          g.beginPath();
          g.moveTo(x + railW + 3, sy + h / 2);
          g.lineTo(x + railW + 3 + (w - railW - 8) * clamp(p2 * 1.4, 0, 1), sy + h / 2);
          g.stroke();
        }
        g.globalAlpha = a * e;
        g.font = "700 7.5px ui-monospace, Menlo, Consolas, monospace";
        g.textAlign = "right";
        g.textBaseline = "middle";
        g.fillStyle = opColor(b.op);
        g.fillText(b.op === 1 ? "REWRITE" : b.op === 2 ? "DROP" : "APPEND", x + w - 6, sy + 6.5);
        g.globalAlpha = a;
      }

      g.globalAlpha = 1;
    }

    function marginish(col) { return Math.max(14, cssW * 0.032) * 0.4; }

    /* ---- the loop ------------------------------------------------------ */

    function reduceMotion() {
      return !!(mqReduce && mqReduce.matches);
    }

    function slowMotion() {
      return reduceMotion() && opts.reducedMotion === "slow";
    }

    function canAnimate() {
      return !stopped && !hidden && inView && (!reduceMotion() || slowMotion());
    }

    function frame(now) {
      raf = 0;
      if (!canAnimate()) return;
      var dt = last ? Math.min((now - last) / 1000, 0.05) : 0.016;
      last = now;
      if (slowMotion()) dt *= 0.3;

      var t0 = global.performance && performance.now ? performance.now() : 0;
      advance(dt);
      draw();
      var t1 = global.performance && performance.now ? performance.now() : 0;
      if (t1 > t0) cpuEma += ((t1 - t0) - cpuEma) * 0.05;

      api.stats.frames++;
      api.stats.cpuMs = cpuEma;
      fpsFrames++;
      if (!fpsSince) fpsSince = now;
      if (now - fpsSince >= 1000) {
        api.stats.fps = (fpsFrames * 1000) / (now - fpsSince);
        fpsFrames = 0;
        fpsSince = now;
      }

      raf = global.requestAnimationFrame(frame);
    }

    function start() {
      if (raf || !canAnimate()) return;
      last = 0;
      raf = global.requestAnimationFrame(frame);
    }

    function stop() {
      if (raf) global.cancelAnimationFrame(raf);
      raf = 0;
    }

    function reconcile() {
      if (canAnimate()) start();
      else {
        stop();
        if (stopped || reduceMotion()) renderStill();
      }
    }

    function renderStill() {
      if (drawnStill) return;
      var left = opts.stillTime;
      while (left > 0) {
        var step = Math.min(left, 0.25);
        advance(step);
        left -= step;
      }
      draw();
      drawnStill = true;
    }

    /* ---- wiring -------------------------------------------------------- */

    function readTheme() {
      var t = doc.documentElement.getAttribute("data-theme");
      if (t === "dark" || t === "light") return t;
      return mqDark && mqDark.matches ? "dark" : "light";
    }

    function onVisibility() {
      hidden = doc.visibilityState === "hidden";
      reconcile();
    }

    function onTheme() {
      themeName = readTheme();
      buildPalette();
      drawnStill = false;
      if (canAnimate()) { draw(); start(); }
      else renderStill();
    }

    function destroy() {
      stopped = true;
      stop();
      doc.removeEventListener("visibilitychange", onVisibility);
      if (themeObserver) themeObserver.disconnect();
      if (resizeObserver) resizeObserver.disconnect();
      if (intersection) intersection.disconnect();
      if (mqDark && mqDark.removeEventListener) mqDark.removeEventListener("change", onTheme);
      if (mqReduce && mqReduce.removeEventListener) mqReduce.removeEventListener("change", reconcile);
      if (fallbackResize) global.removeEventListener("resize", resize);
      delete canvas.__heroBlocks;
    }

    doc.addEventListener("visibilitychange", onVisibility);
    if (mqDark && mqDark.addEventListener) mqDark.addEventListener("change", onTheme);
    if (mqReduce && mqReduce.addEventListener) mqReduce.addEventListener("change", reconcile);

    if (global.MutationObserver) {
      themeObserver = new MutationObserver(function (records) {
        for (var r = 0; r < records.length; r++) {
          if (records[r].attributeName === "data-theme") { onTheme(); return; }
        }
      });
      themeObserver.observe(doc.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }

    if (global.ResizeObserver) {
      resizeObserver = new ResizeObserver(function () { resize(); });
      resizeObserver.observe(canvas);
    } else {
      fallbackResize = true;
      global.addEventListener("resize", resize);
    }

    if (global.IntersectionObserver) {
      intersection = new IntersectionObserver(function (entries) {
        inView = entries[entries.length - 1].isIntersecting;
        reconcile();
      });
      intersection.observe(canvas);
    }

    api.redraw = function () { resize(); };
    Object.defineProperty(api.stats, "blocks", {
      get: function () {
        var n = 0;
        for (var i = 0; i < columns.length; i++) n += columns[i].blocks.length;
        return n;
      }
    });
    Object.defineProperty(api.stats, "edits", { get: function () { return editsFired; } });
    Object.defineProperty(api.stats, "marked", {
      get: function () {
        var n = 0;
        for (var i = 0; i < columns.length; i++) {
          var bs = columns[i].blocks;
          for (var k = 0; k < bs.length; k++) if (bs[k].edited) n++;
        }
        return n;
      }
    });
    Object.defineProperty(api.stats, "cssSize", { get: function () { return [cssW, cssH]; } });

    themeName = readTheme();
    buildPalette();
    canvas.__heroBlocks = api;
    resize();
    if (reduceMotion()) renderStill();
    reconcile();

    return api;
  }

  /* ---------------------------------------------------------------------- */
  /* public surface                                                        */
  /* ---------------------------------------------------------------------- */

  function initAll(root) {
    var scope = root || doc;
    var nodes = scope.querySelectorAll ? scope.querySelectorAll("[data-hero-blocks]") : [];
    var made = [];
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].tagName === "CANVAS") made.push(attach(nodes[i]));
    }
    return made;
  }

  global.HeroBlocks = { version: VERSION, attach: attach, init: initAll };

  function boot() { initAll(doc); }
  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})(window, document);
