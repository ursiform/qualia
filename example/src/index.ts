// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import '../index.css';

import cytoscape from 'cytoscape';
import { Qualia, Connectome } from 'qualia';
import { Specs } from './specs';

function main() {
  const connectome = new Connectome({ spec: Specs.alpha });
  const spec = connectome.dehydrate();
  const header = document.querySelector('main header') as HTMLElement;
  const container = document.getElementById('figure');
  const arrow = 'triangle';
  const elements = spec.nodes
    .map((node, index) => ({
      data: { id: Array.isArray(node) ? node[1] : `${node}-${index}` }
    }))
    .concat(
      spec.edges.map(([source, target]) => ({
        data: { id: `${source}-${target}`, arrow, source, target }
      }))
    );
  const style: cytoscape.Stylesheet[] = [
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
        'target-arrow-color': '#999999'
      }
    }
  ];
  const layout: cytoscape.LayoutOptions = { name: 'grid', rows: 4 };

  cytoscape({ container, elements, style, layout });
  header.textContent = `qualia v${Qualia.version}`;
  (window as any).connectome = connectome;
  console.log('window.connectome', connectome);
}

window.addEventListener('load', main);
