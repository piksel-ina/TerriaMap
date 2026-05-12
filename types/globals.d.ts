declare module "*.svg";
declare module "*.gif";
declare module "*.html" {
  const content: string;
  export default content;
}
declare module "terriajs-cesium/Source/*";
