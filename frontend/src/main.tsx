import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Anchor, createTheme, MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import { App } from './App';

const theme = createTheme({
  components: {
    Anchor: Anchor.extend({
      styles: { root: { fontSize: 'inherit' } },
    }),
  },
});

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Root element not found');

createRoot(rootElement).render(
  <StrictMode>
    <MantineProvider theme={theme}>
      <App />
    </MantineProvider>
  </StrictMode>,
);
