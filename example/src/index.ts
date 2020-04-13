// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Qualia, Connectome } from 'qualia';
import '../index.css';

function main() {
  const header = document.querySelector('main header')!;
  const connectome = new Connectome({
    spec: {
      nodes: [
        'sensory',
        'sensory',
        'interneuron',
        'interneuron',
        'motor',
        'motor'
      ],
      edges: []
    }
  });

  header.textContent = `qualia v${Qualia.version}`;
  (window as any).connectome = connectome;
}

window.addEventListener('load', main);
