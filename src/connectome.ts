// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { PartialJSONObject } from '@lumino/coreutils';
import { IDisposable } from '@lumino/disposable';
import { Graph } from './graph';
import { Interneuron } from './interneuron';
import { MotorNeuron } from './motorneuron';
import { Neuron } from './neuron';
import { SensoryNeuron } from './sensoryneuron';

export class Connectome implements IDisposable {
  constructor(options: Connectome.IOptions = {}) {
    options.spec?.nodes.forEach((spec) => {
      const type = Array.isArray(spec) ? spec[0] : spec;
      const key = Array.isArray(spec) ? spec[1] : undefined;
      switch (type as Neuron.Type) {
        case 'interneuron':
          this.graph.add(new Interneuron(), key);
          break;
        case 'motor':
          this.graph.add(new MotorNeuron(), key);
          break;
        case 'sensory':
          this.graph.add(new SensoryNeuron(), key);
          break;
        default:
          throw new TypeError(`Connectome#constructor: unknown type "${type}"`);
      }
    });
    options.spec?.edges.forEach(([src, dest]) => {
      this.graph.link(src, dest);
    });
  }

  protected graph = new Graph<Neuron>();

  get isDisposed(): boolean {
    return this.graph.isDisposed;
  }

  dispose() {
    this.graph.dispose();
  }
}

export namespace Connectome {
  export interface ISpecification extends PartialJSONObject {
    edges: [string, string][];
    nodes: ([string, string] | string)[];
  }

  export interface IOptions {
    spec?: ISpecification;
  }
}
