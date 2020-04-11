// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Qualia } from './qualia';

export abstract class Neuron {
  abstract type: 'interneuron' | 'motor' | 'sensory';
  abstract async tick(input: Qualia.Matrix): Promise<Qualia.Matrix>;
}
