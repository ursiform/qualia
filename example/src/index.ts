// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Qualia } from 'qualia';
import '../index.css';

function main() {
  const header = document.querySelector('main header')!;

  header.textContent = `qualia v${Qualia.version}`;
}

window.addEventListener('load', main);
