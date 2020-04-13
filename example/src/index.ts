// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Qualia, Connectome } from 'qualia';
import '../index.css';
import { Specs } from './specs';

function main() {
  const header = document.querySelector('main header')!;
  const connectome = new Connectome({ spec: Specs.alpha });

  header.textContent = `qualia v${Qualia.version}`;
  (window as any).connectome = connectome;
}

window.addEventListener('load', main);
