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
    options.spec?.nodes.forEach(spec => {
      const type = Array.isArray(spec) ? spec[0] : spec;
      const key = Array.isArray(spec) ? spec[1] : undefined;
      switch (type) {
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

  dehydrate(): Connectome.Specification {
    const dehydrated: Connectome.Specification = { edges: [], nodes: [] };
    for (let [key, node] of this.graph.entries()) {
      dehydrated.nodes.push([node.value.type, key]);
      for (let [src] of node.in.entries()) {
        dehydrated.edges.push([src, key]);
      }
      for (let [dest] of node.out.entries()) {
        dehydrated.edges.push([key, dest]);
      }
    }
    return dehydrated;
  }

  dispose() {
    this.graph.dispose();
  }
}

export namespace Connectome {
  export type Specification = Private.ISpecification;

  export interface IOptions {
    spec?: Specification;
  }
}

namespace Private {
  export interface ISpecification extends PartialJSONObject {
    edges: [string, string][];
    nodes: ([Neuron.Type, string] | Neuron.Type)[];
  }
}
