// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Connectome } from 'qualia';

export namespace Specs {
  export const alpha: Connectome.Specification = {
    nodes: [
      ['motor', 'm-0'],
      ['motor', 'm-1'],

      ['sensory', 's-0'],
      ['sensory', 's-1'],

      ['interneuron', 'i-0'],
      ['interneuron', 'i-1'],
      ['interneuron', 'i-2'],
      ['interneuron', 'i-3'],
      ['interneuron', 'i-4'],
      ['interneuron', 'i-5'],
      ['interneuron', 'i-6'],
      ['interneuron', 'i-7']
    ],
    edges: [
      ['m-0', 's-0'],

      ['m-1', 's-1'],

      ['s-0', 'i-0'],
      ['s-0', 'i-1'],
      ['s-0', 'i-2'],
      ['s-0', 'i-3'],

      ['s-1', 'i-4'],
      ['s-1', 'i-5'],
      ['s-1', 'i-6'],
      ['s-1', 'i-7'],

      ['i-0', 'm-0'],
      ['i-4', 'm-1'],

      ['i-0', 'i-1'],
      ['i-0', 'i-2'],
      ['i-0', 'i-3'],
      ['i-0', 'i-4'],
      ['i-0', 'i-5'],
      ['i-0', 'i-6'],
      ['i-0', 'i-7'],

      ['i-1', 'i-0'],
      ['i-1', 'i-2'],
      ['i-1', 'i-3'],
      ['i-1', 'i-4'],
      ['i-1', 'i-5'],
      ['i-1', 'i-6'],
      ['i-1', 'i-7']
    ]
  };
}
