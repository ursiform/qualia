// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { ReadonlyJSONObject, UUID } from '@lumino/coreutils';
import { IObservableDisposable } from '@lumino/disposable';
import { ISignal, Signal } from '@lumino/signaling';

export class Graph<T extends IObservableDisposable>
  implements IObservableDisposable {
  get disposed(): ISignal<this, void> {
    return this._disposed;
  }

  get isDisposed(): boolean {
    return this._isDisposed;
  }

  add(node: T, key = UUID.uuid4()) {
    const { graph } = this;

    if (graph.has(key)) {
      console.warn(`Graph#add: ${key} already exists.`);
      return;
    }

    graph.set(key, { node, in: new Map(), out: new Map() });
    node.disposed.connect(() => {
      this.remove(key);
    }, this);
  }

  dispose() {
    if (this._isDisposed) {
      return;
    }
    this.graph.forEach((item) => {
      item.node.dispose();
    });
    this._isDisposed = true;
    this._disposed.emit(undefined);
  }

  link(src: string, dest: string, metadata?: ReadonlyJSONObject) {
    const { graph } = this;

    if (!graph.has(src)) {
      throw new ReferenceError(`Graph#link: ${src} does not exist.`);
    }
    if (!graph.has(dest)) {
      throw new ReferenceError(`Graph#link: ${dest} does not exist.`);
    }

    graph.get(src)!.out.set(dest, metadata || undefined);
    graph.get(dest)!.in.set(src, metadata || undefined);
  }

  remove(key: string) {
    const { graph } = this;

    if (!graph.has(key)) {
      console.warn(`Graph#remove: ${key} does not exist.`);
      return;
    }

    const node = graph.get(key)!;

    node.in.forEach((_, src) => {
      this.unlink(src, key);
    });
    node.out.forEach((_, dest) => {
      this.unlink(key, dest);
    });
    graph.delete(key);
    Signal.disconnectBetween(node, this);
  }

  unlink(src: string, dest: string) {
    const { graph } = this;

    if (!graph.has(src)) {
      throw new ReferenceError(`Graph#unlink: ${src} does not exist.`);
    }
    if (!graph.has(dest)) {
      throw new ReferenceError(`Graph#unlink: ${dest} does not exist.`);
    }

    graph.get(src)!.out.delete(dest);
    graph.get(dest)!.in.delete(src);
  }

  protected graph = new Map<
    string,
    {
      node: T;
      in: Map<string, ReadonlyJSONObject | undefined>;
      out: Map<string, ReadonlyJSONObject | undefined>;
    }
  >();

  private _disposed = new Signal<this, void>(this);
  private _isDisposed = false;
}
