declare module "@jupyterlab/mainmenu" {
  import { Token } from "@lumino/coreutils";
  import { Menu } from "@lumino/widgets";

  export interface IMainMenu {
    addMenu(menu: Menu, options?: { rank?: number }): void;
  }

  export const IMainMenu: Token<IMainMenu>;
}
