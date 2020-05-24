// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Neuron } from './neuron';

export class Interneuron extends Neuron {
  readonly type: Neuron.Type = 'interneuron';
  input(data: Neuron.Matrix): void {
    // no-op
  }
}
