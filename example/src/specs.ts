// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Connectome } from 'qualia';

export namespace Specs {
  export const alpha: Connectome.ISpecification = {
    nodes: [
      ['sensory', 'S1'],
      ['motor', 'M1'],
      ['sensory', 'S2'],
      ['motor', 'M2'],
      ['interneuron', 'I1'],
      ['interneuron', 'I2'],
      ['interneuron', 'I3'],
      ['interneuron', 'I4'],
      ['interneuron', 'I5'],
      ['interneuron', 'I6'],
      ['interneuron', 'I7'],
      ['interneuron', 'I8']
    ],
    edges: [
      ['S1', 'M1'],
      ['S1', 'I1'],

      ['S2', 'M2'],
      ['S2', 'I1'],

      ['M1', 'S1'],

      ['M2', 'S2'],

      ['I1', 'I2'],
      ['I1', 'I3'],
      ['I1', 'I4'],
      ['I1', 'I5'],
      ['I1', 'I6'],
      ['I1', 'I7'],
      ['I1', 'I8'],

      ['I2', 'I1']
    ]
  };
}
