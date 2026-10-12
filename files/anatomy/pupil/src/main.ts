import { mount } from 'svelte';
import '$face/app.css';
import App from './App.svelte';

mount(App, { target: document.getElementById('app')! });
