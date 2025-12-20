import { LabIcon } from "@jupyterlab/ui-components";

// Inline SVG for the Calkit sidebar icon, using the provided MathJax-generated
// paths for C^{\dot{k}}, colored via currentColor to match JupyterLab icons.
const calkitIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 -1123.6 1263.7 1145.6" aria-hidden="true">
  <defs>
    <path id="MJX-11-NCM-I-1D436" d="M148 218C148 346 204 476 267 548C318 607 406 666 505 666C609 666 660 587 660 479C660 470 657 438 657 429C657 420 663 415 676 415C681 415 685 416 688 417C693 424 696 431 698 438L760 691C760 700 755 705 745 705C741 705 735 701 727 692L662 619C623 676 568 705 497 705C442 705 388 692 333 667C222 615 141 533 89 421C63 366 50 310 50 253C50 173 75 108 126 56C177 4 242-22 322-22C401-22 473 7 538 64C565 87 588 115 607 146C634 191 648 222 648 241C648 250 643 255 632 255C623 255 618 251 616 242C595 177 562 125 517 88C460 41 400 17 338 17C218 17 148 98 148 218Z" />
    <path id="MJX-11-NCM-I-1D458" d="M409 353C409 327 423 314 450 314C485 314 508 345 508 379C508 418 476 445 437 445C392 445 344 415 291 356C250 311 217 282 190 269L291 679C289 688 287 694 274 694C242 694 166 685 154 684C139 682 132 675 132 660C132 650 141 645 159 645C178 645 204 646 204 632L59 43C56 32 55 25 55 21C55 0 66-11 87-11C104-11 117-3 124 12C129 21 147 92 179 226C231 221 286 196 286 146C286 131 279 101 279 91C279 34 316-11 373-11C431-11 470 41 490 145C490 154 485 159 475 159C466 159 460 152 457 138C435 59 408 19 375 19C357 19 348 33 348 61C348 77 360 131 360 147C360 204 314 239 221 253C244 269 270 292 298 322C326 352 346 371 359 382C386 404 412 415 435 415C445 415 453 413 459 409C432 404 409 379 409 353Z" />
    <path id="MJX-11-NCM-N-2D9" d="M192 604C192 633 168 657 139 657C110 657 85 633 85 604C85 575 109 551 138 551C167 551 192 575 192 604Z" />
  </defs>
  <g fill="currentColor" stroke="none" stroke-width="0" transform="scale(1,-1)">
    <g data-mml-node="math">
      <g data-mml-node="msup" transform="translate(0,0)">
        <use xlink:href="#MJX-11-NCM-I-1D436" />
        <g transform="translate(845.3,413) scale(0.707)">
          <g transform="translate(0,0)">
            <use xlink:href="#MJX-11-NCM-I-1D458" />
            <g transform="translate(249.5,248) translate(-139 0)">
              <use xlink:href="#MJX-11-NCM-N-2D9" />
            </g>
          </g>
        </g>
      </g>
    </g>
  </g>
</svg>`;

export const calkitIcon = new LabIcon({
  name: "calkit:sidebar",
  svgstr: calkitIconSvg,
});
