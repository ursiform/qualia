// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import '../index.css';

import cytoscape from 'cytoscape';
import { Qualia, Connectome } from 'qualia';
import { Specs } from './specs';

function main() {
  const spec = Specs.alpha;
  const connectome = new Connectome({ spec });
  const header = document.querySelector('main header') as HTMLElement;
  const figure = document.getElementById('figure');
  const arrow = 'triangle';
  const nodes = spec.nodes.map((node, index) => ({
    data: { id: Array.isArray(node) ? node[1] : `${node}-${index}` }
  }));
  const edges = spec.edges.map(([source, target]) => ({
    data: { id: `${source}-${target}`, arrow, source, target }
  }));

  (window as any).connectome = connectome;
  cytoscape({
    container: figure,
    elements: nodes.concat(edges),
    style: [
      {
        selector: 'node',
        style: {
          'background-color': '#888888',
          label: 'data(id)'
        }
      },
      {
        selector: 'edge',
        style: {
          width: 2,
          'curve-style': 'straight',
          'line-color': '#aaaaaa'
        }
      },
      {
        selector: 'edge[arrow]',
        style: {
          'target-arrow-shape': 'triangle',
          'target-arrow-color': '#aaaaaa'
        }
      }
    ],
    layout: { name: 'grid', rows: 5 }
  });
  header.textContent = `qualia v${Qualia.version}`;
  console.log('connectome', connectome);
}

window.addEventListener('load', main);
